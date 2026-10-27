"""Stops, targets and time stops for open REFERENCE_LAG positions.

The monitor watches every open ``Position`` and asks the engine to close it
when the market reaches its hard stop, its target, or the position has been
held for ``max_hold_s``:

  long  (entry side BUY):  exit when ``bid <= stop`` ("stop"), ``bid >= target``
                           ("target"), or held >= ``max_hold_s`` ("time")
  short (entry side SELL): exit when ``ask >= stop`` ("stop"), ``ask <= target``
                           ("target"), or held >= ``max_hold_s`` ("time")

Checks run in that order, so a quote that is through the stop reports "stop"
even if the time stop has also elapsed.

Exits are never blocked (invariant 6): an exit is priced from the latest quote
the monitor can find even when it is older than ``risk.max_quote_age_ms``, or
when the book has dropped the venue after a disconnect (the monitor keeps its
own copy of the last valid quote per venue/symbol). Only invalid quotes
(crossed, non-positive) are ignored, because a limit derived from them could
be arbitrarily wrong.

Once an exit triggers, the position is *exiting*: a partial fill keeps it open
and the remainder is retried on the next quote regardless of whether the stop
or target condition still holds. After ``max_exit_attempts`` attempts that did
not close it, the monitor emits a ``RESIDUAL`` report (the risk manager trips
the kill switch on it) and stops managing the position; it is kept in
``residuals`` for the operator. An exit whose outcome is ``UNKNOWN`` is parked
in ``unresolved`` instead of retried, because re-sending could double the exit
if the unknown order actually filled. A position the engine reports CLOSED
with qty still open was closed as *dust* (what is left is below the venue's
lot or min notional, so no order can sell it): it is kept in ``dust`` for the
operator and the accounting, and is not a kill-switch event.
"""

from __future__ import annotations

import logging
from typing import Protocol

from ..clock import Clock
from ..config import BotConfig
from ..feeds.base import QuoteBook
from ..models import ExecutionOutcome, ExecutionReport, Position, Quote, Side

log = logging.getLogger(__name__)

# Float timestamps carry ~0.2us of rounding at epoch scale; the time stop
# tolerates 1us, matching the scanners and the risk manager.
_TIMER_EPS_S = 1e-6
# A position whose remaining qty is at or below this is considered flat.
_QTY_EPS = 1e-12

REASON_STOP = "stop"
REASON_TARGET = "target"
REASON_TIME = "time"


class ExitEngine(Protocol):
    """The part of ``ExecutionEngine`` the monitor needs (see DESIGN.md, execution)."""

    async def exit_position(self, position: Position, reason: str, quote: Quote) -> ExecutionReport:
        """IOC for the open qty on the opposite side; reduces ``position.qty`` by what filled."""
        ...


def exit_reason(position: Position, quote: Quote, now: float) -> str | None:
    """Why ``position`` should be closed at ``quote`` and time ``now`` (None: keep holding)."""
    if position.side is Side.BUY:
        if quote.bid <= position.stop_price:
            return REASON_STOP
        if quote.bid >= position.target_price:
            return REASON_TARGET
    else:
        if quote.ask >= position.stop_price:
            return REASON_STOP
        if quote.ask <= position.target_price:
            return REASON_TARGET
    if time_stop_due(position, now):
        return REASON_TIME
    return None


def time_stop_due(position: Position, now: float) -> bool:
    """True once ``position`` has been held for ``max_hold_s`` (1us float tolerance)."""
    return now - position.opened_ts >= position.max_hold_s - _TIMER_EPS_S


class PositionMonitor:
    def __init__(
        self,
        cfg: BotConfig,
        engine: ExitEngine,
        clock: Clock,
        *,
        max_exit_attempts: int = 5,
    ) -> None:
        if max_exit_attempts < 1:
            raise ValueError("max_exit_attempts must be >= 1")
        self._cfg = cfg
        self._engine = engine
        self._clock = clock
        self._max_attempts = max_exit_attempts
        self._open: dict[str, Position] = {}  # insertion-ordered: deterministic exit order
        self._exit_reason: dict[str, str] = {}  # position id -> reason of the first trigger
        self._attempts: dict[str, int] = {}  # exit calls that left the position open
        self._last_attempt_ts: dict[str, float] = {}  # ts_local of the quote used last
        self._in_flight: set[str] = set()  # guards against concurrent on_quote / on_tick exits
        self._warned_no_quote: set[str] = set()
        self._last_quote: dict[tuple[str, str], Quote] = {}
        self._residuals: list[Position] = []
        self._unresolved: list[Position] = []
        self._dust: list[Position] = []

    # ------------------------------------------------------------------ state

    def open(self, position: Position) -> None:
        if position.id in self._open:
            raise ValueError(f"position {position.id} is already monitored")
        if not position.qty > 0:
            raise ValueError(f"position {position.id} has no open qty ({position.qty})")
        self._open[position.id] = position
        self._attempts[position.id] = position.exit_attempts
        log.info(
            "monitor: opened %s %s %s %s @ %s stop=%s target=%s max_hold=%ss",
            position.id, position.venue, position.side.value, position.qty, position.entry_price,
            position.stop_price, position.target_price, position.max_hold_s,
        )

    @property
    def positions(self) -> tuple[Position, ...]:
        """Positions still being managed (open, possibly mid-exit)."""
        return tuple(self._open.values())

    @property
    def residuals(self) -> tuple[Position, ...]:
        """Positions given up on after ``max_exit_attempts`` (a RESIDUAL report was emitted)."""
        return tuple(self._residuals)

    @property
    def unresolved(self) -> tuple[Position, ...]:
        """Positions whose exit came back UNKNOWN: reconcile manually before trading again."""
        return tuple(self._unresolved)

    @property
    def dust(self) -> tuple[Position, ...]:
        """Positions closed with an unsellable remainder (below the lot or min notional) still in the account."""
        return tuple(self._dust)

    def exiting(self, position_id: str) -> str | None:
        """Reason an exit was triggered for ``position_id``, or None if it is still held."""
        return self._exit_reason.get(position_id)

    # ------------------------------------------------------------------ events

    async def on_quote(self, quote: Quote) -> list[ExecutionReport]:
        """Check every position on ``quote``'s venue/symbol against it; exit those that trigger."""
        if not quote.is_valid():
            return []
        key = (quote.venue, quote.symbol)
        prev = self._last_quote.get(key)
        if prev is None or quote.ts_local >= prev.ts_local:
            self._last_quote[key] = quote
        latest = self._last_quote[key]  # an out-of-order quote never replaces a newer one
        reports: list[ExecutionReport] = []
        for pos in [p for p in self._open.values() if (p.venue, p.symbol) == key]:
            reports.extend(await self._evaluate(pos, latest))
        return reports

    async def on_tick(self, book: QuoteBook) -> list[ExecutionReport]:
        """Time stops (and any other trigger) without a new quote, priced from the latest quote.

        A position already mid-exit is retried here only when a quote newer than
        the one its last attempt used is available; otherwise it waits for the
        next quote, as a retry at the same price would most likely fail again.
        """
        reports: list[ExecutionReport] = []
        for pos in list(self._open.values()):
            quote = self._latest_quote(pos, book)
            if quote is None:
                if time_stop_due(pos, self._clock.now()) and pos.id not in self._warned_no_quote:
                    self._warned_no_quote.add(pos.id)
                    log.warning("monitor: %s time stop due but no quote for %s %s; cannot price the exit",
                                pos.id, pos.venue, pos.symbol)
                continue
            if pos.id in self._exit_reason and quote.ts_local <= self._last_attempt_ts.get(pos.id, float("-inf")):
                continue
            reports.extend(await self._evaluate(pos, quote))
        return reports

    # ------------------------------------------------------------------ internals

    def _latest_quote(self, pos: Position, book: QuoteBook) -> Quote | None:
        """Newest valid quote from the book or the monitor's own cache, regardless of age."""
        cached = self._last_quote.get((pos.venue, pos.symbol))
        live = book.get(pos.venue, pos.symbol)
        if live is not None and not live.is_valid():
            live = None
        if live is None:
            return cached
        if cached is None or live.ts_local >= cached.ts_local:
            return live
        return cached

    async def _evaluate(self, pos: Position, quote: Quote) -> list[ExecutionReport]:
        if pos.id in self._in_flight or pos.id not in self._open:
            return []
        now = self._clock.now()
        reason = self._exit_reason.get(pos.id) or exit_reason(pos, quote, now)
        if reason is None:
            return []
        self._exit_reason.setdefault(pos.id, reason)
        return await self._exit(pos, reason, quote, now)

    async def _exit(self, pos: Position, reason: str, quote: Quote, now: float) -> list[ExecutionReport]:
        age_s = quote.age(now)
        stale = age_s * 1000.0 > self._cfg.risk.max_quote_age_ms
        log.info("monitor: exiting %s (%s) qty=%s on %s quote age=%.3fs%s",
                 pos.id, reason, pos.qty, pos.venue, age_s, " (stale; exits are never blocked)" if stale else "")
        self._in_flight.add(pos.id)
        self._last_attempt_ts[pos.id] = quote.ts_local
        try:
            report = await self._engine.exit_position(pos, reason, quote)
        except Exception as e:  # the engine should not raise; if it does the order's fate is unknown
            log.exception("monitor: exit_position raised for %s", pos.id)
            report = ExecutionReport(
                signal_id=pos.signal_id,
                outcome=ExecutionOutcome.UNKNOWN,
                started_ts=now,
                finished_ts=self._clock.now(),
                position_id=pos.id,
                notes=[f"exit ({reason}) raised {type(e).__name__}: {e}; order state unknown"],
            )
        finally:
            self._in_flight.discard(pos.id)
        if stale:
            report.notes.append(f"exit priced from a stale quote (age {age_s:.3f}s)")
        reports = [report]

        if report.outcome is ExecutionOutcome.CLOSED or pos.qty <= _QTY_EPS:
            self._forget(pos.id)
            if pos.qty > _QTY_EPS:
                self._dust.append(pos)
                log.warning("monitor: closed %s (%s) with %s %s of dust left on %s", pos.id, reason, pos.qty,
                            pos.symbol, pos.venue)
            else:
                log.info("monitor: closed %s (%s)", pos.id, reason)
            return reports
        if report.outcome is ExecutionOutcome.UNKNOWN:
            self._forget(pos.id)
            self._unresolved.append(pos)
            report.notes.append(f"position {pos.id} parked: exit state unknown, reconcile manually")
            log.error("monitor: exit of %s came back UNKNOWN; position parked for manual reconciliation", pos.id)
            return reports

        attempts = max(self._attempts.get(pos.id, 0) + 1, pos.exit_attempts)
        self._attempts[pos.id] = attempts
        if attempts >= self._max_attempts:
            reports.append(self._residual_report(pos, reason, quote, attempts))
            self._forget(pos.id)
            self._residuals.append(pos)
            log.error("monitor: %s still open (%s %s) after %d exit attempts: RESIDUAL",
                      pos.id, pos.qty, pos.symbol, attempts)
        else:
            log.warning("monitor: %s exit attempt %d/%d left qty=%s open; retrying on the next quote",
                        pos.id, attempts, self._max_attempts, pos.qty)
        return reports

    def _residual_report(self, pos: Position, reason: str, quote: Quote, attempts: int) -> ExecutionReport:
        """RESIDUAL for what is still open, marked to mid net of the entry fee not yet charged.

        The engine charges each closed slice its share of ``entry_fee`` (the OPENED
        report books none of it), so the remaining ``pos.entry_fee`` belongs here.
        """
        now = self._clock.now()
        signed = pos.side.sign * pos.qty
        mark = signed * (quote.mid - pos.entry_price) - pos.entry_fee
        return ExecutionReport(
            signal_id=pos.signal_id,
            outcome=ExecutionOutcome.RESIDUAL,
            residual_qty=signed,
            realized_pnl=mark,
            started_ts=now,
            finished_ts=now,
            position_id=pos.id,
            notes=[
                (
                    f"exit ({reason}) failed after {attempts} attempts: {pos.qty} {pos.symbol} still open "
                    f"on {pos.venue}; manual intervention required"
                ),
                f"residual marked to mid {quote.mid}, net of its remaining entry fee {pos.entry_fee}",
            ],
        )

    def _forget(self, position_id: str) -> None:
        self._open.pop(position_id, None)
        self._exit_reason.pop(position_id, None)
        self._attempts.pop(position_id, None)
        self._last_attempt_ts.pop(position_id, None)
        self._warned_no_quote.discard(position_id)


__all__ = [
    "REASON_STOP",
    "REASON_TARGET",
    "REASON_TIME",
    "ExitEngine",
    "PositionMonitor",
    "exit_reason",
    "time_stop_due",
]
