"""The bot: market data -> risk gate -> exits -> scanners -> risk check -> execution.

``Bot.handle_event`` is the single entry point for market data and follows the
DESIGN.md data flow. For each quote, in this order:

1. ``QuoteBook.update``. Out-of-order quotes stop here. Invalid (crossed or
   non-positive) quotes are not stored but still close the liquidity gate.
2. ``RiskManager.on_quote`` (liquidity gate).
3. ``PositionMonitor.on_quote``: stops, targets and time exits run BEFORE any
   new entry, and keep running while the kill switch is tripped (exits are
   never blocked, invariant 6).
4. The scanners. Every signal is journaled (``"signal"``), checked by
   ``RiskManager.check`` and its decision journaled (``"risk"``, same
   ``signal_id``) before anything is sent.
5. Approved signals are executed (``ExecutionEngine.execute`` for
   cross-venue, ``enter`` for reference-lag). Every report goes to
   ``RiskManager.on_execution`` and the journal (``"execution"``). A tripped
   kill switch is journaled once (``"halt"``) and alerted; RESIDUAL and
   UNKNOWN outcomes are alerted too.

A ``FeedStatus(connected=False)`` (including the feed's ``seq_reset`` resync)
drops the venue's quotes from the book and makes it untradable until it
reconnects.

Executions run inline (awaited inside ``handle_event``) in backtests, so a
replay is deterministic. Live, each runs as an asyncio task with at most one
in-flight execution per symbol: a signal for a symbol that is still executing
is journaled with the decision reason ``in_flight`` and dropped. Inline, the
same gate is applied in simulated time: a signal from a quote received
(``ts_local``) before the previous execution of its symbol finished is
``in_flight`` too, because live it would have arrived mid-execution. Without
clients the bot is scan-only: signals and risk decisions are journaled and
nothing is ever sent.

The journal is the audit trail, but writing it must never strand a trade: a
failed write is logged, alerted once and trips the kill switch
(``journal_error``); the bot keeps managing exits. Alerts are sent before the
matching journal write, and a filled position is handed to the
``PositionMonitor`` before its report is recorded. An execution task that
raises anyway trips the kill switch (``internal_error``) and is alerted.

Inventory that backs an open directional position (base for a long, the
quote cost of buying back a short) is reserved in the Portfolio, so a
cross-venue arb is never sized from coins a position will need for its exit.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from .alerts import Alerter, LogAlerter
from .clock import Clock
from .config import BotConfig
from .execution.base import ExchangeClient
from .execution.engine import ExecutionEngine
from .execution.monitor import PositionMonitor
from .feeds.base import BookView, Feed, QuoteBook
from .feeds.ws import merge_feeds
from .journal import Journal, NullJournal
from .models import (
    ExecutionOutcome,
    ExecutionReport,
    FeedEvent,
    FeedStatus,
    IdFactory,
    Position,
    Quote,
    Side,
    Signal,
    SignalKind,
    split_symbol,
)
from .portfolio import Portfolio
from .risk import RiskDecision, RiskManager
from .signal import CrossVenueScanner, ReferenceLagScanner

log = logging.getLogger(__name__)

IN_FLIGHT = "in_flight"  # decision reason: an execution for this symbol is still running (inline: in sim time)
INTERNAL_ERROR = "internal_error"  # kill-switch cause when handling an event raised
JOURNAL_ERROR = "journal_error"  # kill-switch cause when a journal write failed
_BUSY_EPS_S = 1e-9


def portfolio_from_config(cfg: BotConfig) -> Portfolio:
    """Portfolio seeded with each venue's ``starting_balances`` (paper inventory)."""
    return Portfolio({v.name: dict(v.starting_balances) for v in cfg.venues})


@dataclass(slots=True)
class BotCounters:
    """Running totals, cheap enough to keep for a bot that runs for weeks."""

    events: int = 0
    quotes: int = 0
    dropped_quotes: int = 0  # out of order or invalid (not stored in the book)
    feed_status: int = 0
    signals: int = 0
    approved: int = 0
    executions: int = 0  # approved signals handed to the engine
    errors: int = 0
    decisions: dict[str, int] = field(default_factory=dict)  # reason -> count ("ok" when approved)
    outcomes: dict[str, int] = field(default_factory=dict)  # ExecutionOutcome value -> count

    def summary(self) -> dict[str, object]:
        return {
            "events": self.events,
            "quotes": self.quotes,
            "dropped_quotes": self.dropped_quotes,
            "feed_status": self.feed_status,
            "signals": self.signals,
            "approved": self.approved,
            "executions": self.executions,
            "errors": self.errors,
            "decisions": dict(self.decisions),
            "outcomes": dict(self.outcomes),
        }


@dataclass(slots=True)
class BotHistory:
    """Every signal, decision and report, in order (kept for backtests; unbounded)."""

    signals: list[Signal] = field(default_factory=list)
    decisions: list[tuple[Signal, RiskDecision]] = field(default_factory=list)
    reports: list[ExecutionReport] = field(default_factory=list)


def _bump(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


class Bot:
    """Wires QuoteBook, RiskManager, scanners, ExecutionEngine and PositionMonitor together."""

    def __init__(
        self,
        cfg: BotConfig,
        *,
        clients: Mapping[str, ExchangeClient] | None,
        clock: Clock,
        journal: Journal | None,
        portfolio: Portfolio,
        inline_execution: bool,
        book: QuoteBook | None = None,
        alerter: Alerter | None = None,
        max_exit_attempts: int = 5,
        tick_interval_s: float = 0.5,
        keep_history: bool = False,
        label: str = "",
        execution_book: BookView | None = None,
    ) -> None:
        self.cfg = cfg
        self.clock = clock
        self.journal = journal if journal is not None else NullJournal()
        self.portfolio = portfolio
        self.book = book if book is not None else QuoteBook()
        self.alerter: Alerter = alerter if alerter is not None else LogAlerter()
        self.label = label or cfg.mode
        self.inline_execution = inline_execution
        self.tick_interval_s = tick_interval_s
        self.ids = IdFactory()  # per bot: a run's ids start at 1 whatever ran before in this process
        self.risk = RiskManager(cfg, portfolio, clock)
        self.scanner = CrossVenueScanner(cfg, clock, ids=self.ids)
        self.lag_scanner = ReferenceLagScanner(cfg, clock, ids=self.ids) if cfg.reference_lag.enabled else None
        self.engine: ExecutionEngine | None = None
        self.monitor: PositionMonitor | None = None
        if clients:
            missing = [v.name for v in cfg.venues if v.name not in clients]
            if missing:
                raise ValueError(f"no exchange client for venue(s) {missing}")
            self.engine = ExecutionEngine(cfg, clients, portfolio,
                                          execution_book if execution_book is not None else self.book,
                                          clock, ids=self.ids)
            self.monitor = PositionMonitor(cfg, self.engine, clock, max_exit_attempts=max_exit_attempts)
            portfolio.set_reservations(self._reservations)
        self.counters = BotCounters()
        self.history: BotHistory | None = BotHistory() if keep_history else None
        self._inflight: dict[str, asyncio.Task[None]] = {}
        self._busy_until: dict[str, float] = {}  # inline: simulated time each symbol's last execution ended
        self._halt_seen: str | None = None
        self._journal_failures = 0
        # An execution is bounded by its leg timeouts: two legs, a hedge and an
        # unwind, each possibly followed by a reconciliation query.
        self.execution_grace_s = 8 * cfg.execution.leg_timeout_ms / 1000.0 + 5.0

    @property
    def scan_only(self) -> bool:
        return self.engine is None

    @property
    def in_flight(self) -> tuple[str, ...]:
        """Symbols with an execution still running (live mode)."""
        return tuple(s for s, t in self._inflight.items() if not t.done())

    def _busy_at(self, symbol: str, received: float | None) -> bool:
        """Inline execution: was ``symbol`` still executing (simulated time) when the quote was received?"""
        if not self.inline_execution or received is None:
            return False
        return received < self._busy_until.get(symbol, -math.inf) - _BUSY_EPS_S

    def _reservations(self) -> dict[str, dict[str, float]]:
        """Inventory each open directional position needs for its exit: venue -> asset -> qty."""
        out: dict[str, dict[str, float]] = {}
        m = self.monitor
        if m is None:
            return out
        u = self.cfg.execution.unwind_slippage_bps / 1e4
        for p in (*m.positions, *m.residuals, *m.unresolved):
            base, quote = split_symbol(p.symbol)
            held = out.setdefault(p.venue, {})
            if p.side is Side.BUY:  # a long sells its base to exit
                held[base] = held.get(base, 0.0) + p.qty
            else:  # a short buys back: keep the quote to do it at its stop, through the unwind band
                fee = self.cfg.venue(p.venue).taker_fee_bps / 1e4
                cost = p.qty * max(p.stop_price, p.entry_price) * (1 + u) * (1 + fee)
                held[quote] = held.get(quote, 0.0) + cost
        return out

    # ------------------------------------------------------------------ journal

    def _record(self, kind: str, payload: Any) -> None:
        """Journal a record. A failed write never propagates: it is logged, alerted once and halts entries."""
        try:
            self.journal.record(kind, self.clock.now(), payload)
        except Exception as e:  # noqa: BLE001 - the audit trail must not take trading down with it
            self.counters.errors += 1
            self._journal_failures += 1
            n = self._journal_failures
            if n == 1 or n % 1000 == 0:
                log.error("journal write of a %s record failed (%d so far): %s: %s", kind, n, type(e).__name__, e)
            if n == 1:
                self.alerter.send(f"arbbot [{self.label}] journal write failed ({type(e).__name__}): the audit "
                                  "trail is incomplete. New entries are blocked; exits still run.")
            if self.risk.halt_reason is None:
                self.risk.trip(JOURNAL_ERROR)
            self._check_halt(f"journal write of a {kind} record failed")

    def record_start(self, extra: Mapping[str, Any] | None = None) -> None:
        """Journal the ``start`` record that opens a run (``run`` and backtests call it)."""
        self._record("start", {
            "mode": self.label,
            "scan_only": self.scan_only,
            "venues": [v.name for v in self.cfg.venues],
            **dict(extra or {}),
        })

    # ------------------------------------------------------------------ events

    async def handle_event(self, ev: FeedEvent) -> None:
        self.counters.events += 1
        if isinstance(ev, FeedStatus):
            self._on_status(ev)
        else:
            await self._on_quote(ev)

    def _on_status(self, status: FeedStatus) -> None:
        self.counters.feed_status += 1
        if not status.connected:
            self.book.invalidate_venue(status.venue)  # never trade on a frozen book (invariant 2)
            log.warning("%s feed down: %s", status.venue, status.reason or "disconnected")
        else:
            log.info("%s feed up%s", status.venue, f" ({status.reason})" if status.reason else "")
        self.risk.on_feed_status(status)
        self._record("feed", status)

    async def _on_quote(self, quote: Quote) -> None:
        self.counters.quotes += 1
        if not self.book.update(quote):
            self.counters.dropped_quotes += 1
            if not quote.is_valid():
                self.risk.on_quote(quote)  # a crossed / empty book closes the liquidity gate
            return  # out of order: the book already holds a newer quote
        self.risk.on_quote(quote)
        if self.monitor is not None:
            for report in await self.monitor.on_quote(quote):  # exits before any new entry
                self._on_report(report)
        signals = self.scanner.on_quote(quote, self.book, self.portfolio)
        if self.lag_scanner is not None:
            signals += self.lag_scanner.on_quote(quote, self.book, self.portfolio)
        for sig in signals:
            await self._on_signal(sig, received=quote.ts_local)

    async def tick(self) -> None:
        """Time stops (and retries of pending exits) without a new quote."""
        if self.monitor is None:
            return
        for report in await self.monitor.on_tick(self.book):
            self._on_report(report)

    # ------------------------------------------------------------------ signals

    async def _on_signal(self, sig: Signal, *, received: float | None = None) -> None:
        self.counters.signals += 1
        if self.history is not None:
            self.history.signals.append(sig)
        self._record("signal", {"signal": sig})

        if sig.symbol in self.in_flight or self._busy_at(sig.symbol, received):
            decision = RiskDecision(False, 0.0, IN_FLIGHT)
        else:
            open_positions = len(self.monitor.positions) if self.monitor is not None else 0
            decision = self.risk.check(sig, self.book, open_positions=open_positions)
        _bump(self.counters.decisions, decision.reason)
        if self.history is not None:
            self.history.decisions.append((sig, decision))
        self._record("risk", {
            "signal_id": sig.id,
            "market": sig.market,
            "approved": decision.approved,
            "size": decision.size,
            "reason": decision.reason,
            "scan_only": self.scan_only,
        })
        self._check_halt(f"risk check of {sig.id}")
        if not decision.approved:
            return
        self.counters.approved += 1
        if self.engine is None:
            return  # scan-only: never execute
        self.counters.executions += 1
        if self.inline_execution:
            await self._execute(sig, decision.size)
            self._busy_until[sig.symbol] = self.clock.now()
            return
        task = asyncio.create_task(self._execute(sig, decision.size), name=f"execute-{sig.id}")
        self._inflight[sig.symbol] = task
        task.add_done_callback(partial(self._execution_done, sig.symbol))

    def _execution_done(self, symbol: str, task: asyncio.Task[None]) -> None:
        if self._inflight.get(symbol) is task:
            del self._inflight[symbol]
        if task.cancelled():
            return
        exc = task.exception()  # retrieved here, so it can never go unnoticed
        if exc is None:
            return
        log.error("execution task %s failed", task.get_name(), exc_info=exc)
        self.counters.errors += 1
        self.alerter.send(f"arbbot [{self.label}] execution {task.get_name()} failed ({type(exc).__name__}): "
                          "its orders may have filled. Check positions and balances on the venues.")
        self.trip(INTERNAL_ERROR)

    async def _execute(self, sig: Signal, size: float) -> None:
        assert self.engine is not None and self.monitor is not None
        started = self.clock.now()
        position: Position | None = None
        try:
            if sig.kind is SignalKind.CROSS_VENUE:
                report = await self.engine.execute(sig, size)
            else:
                report, position = await self.engine.enter(sig, size)
        except Exception as e:
            # The engine reports venue problems instead of raising, so this is a
            # bug or a misconfiguration and we cannot tell whether an order went
            # out: report UNKNOWN, which trips the kill switch.
            log.exception("execution of %s raised", sig.id)
            self.counters.errors += 1
            report = ExecutionReport(
                sig.id,
                ExecutionOutcome.UNKNOWN,
                started_ts=started,
                finished_ts=self.clock.now(),
                notes=[f"execution raised {type(e).__name__}: {e}; order state unknown, reconcile manually"],
            )
        if position is not None:  # monitored first: nothing after this may leave it without a stop
            try:
                self.monitor.open(position)
            except Exception:
                log.exception("could not monitor position %s", position.id)
                self.counters.errors += 1
                self.trip(INTERNAL_ERROR)
                self.alerter.send(f"arbbot [{self.label}] position {position.id} ({position.side.value} "
                                  f"{position.qty:g} {position.symbol} on {position.venue}) is NOT monitored: "
                                  "no stop, target or time exit. Close it manually.")
        self._on_report(report)

    # ------------------------------------------------------------------ reports and halts

    def _on_report(self, report: ExecutionReport) -> None:
        _bump(self.counters.outcomes, report.outcome.value)
        if self.history is not None:
            self.history.reports.append(report)
        self.risk.on_execution(report)
        if report.outcome in (ExecutionOutcome.RESIDUAL, ExecutionOutcome.UNKNOWN):
            what = "position" if report.position_id else "signal"
            ref = report.position_id or report.signal_id
            self.alerter.send(
                f"arbbot [{self.label}] {report.outcome.value.upper()} on {what} {ref}: "
                f"residual {report.residual_qty:+g}, realized {report.realized_pnl:+.4f}. "
                "Reconcile on the venue manually."
            )
        self._record("execution", report)
        self._check_halt(f"{report.outcome.value} report for {report.signal_id}")

    def _check_halt(self, context: str) -> None:
        reason = self.risk.halt_reason
        if reason is None:
            self._halt_seen = None
            return
        if reason == self._halt_seen:
            return
        self._halt_seen = reason
        log.error("kill switch tripped: %s (%s)", reason, context)
        self.alerter.send(
            f"arbbot [{self.label}] kill switch tripped: {reason} ({context}). "
            "New entries are blocked, exits still run; an operator reset is required."
        )
        self._record("halt", {"reason": reason, "context": context})

    def trip(self, reason: str) -> None:
        """Operator/kill-switch hook: trip the risk manager and journal + alert it once."""
        self.risk.trip(reason)
        self._check_halt(f"trip({reason or 'manual'})")

    # ------------------------------------------------------------------ live loop

    async def run(self, feeds: Sequence[Feed], stop_event: asyncio.Event) -> None:
        """Consume ``feeds`` until ``stop_event`` is set (or every feed ends), then shut down.

        Shutdown stops the feeds, lets the event being handled finish, waits
        for in-flight executions (bounded by their leg timeouts) and reports
        any position still open. Feed errors propagate after shutdown.
        """
        feeds = list(feeds)
        self.record_start()
        pump = asyncio.create_task(self._pump(feeds), name="bot-pump")
        ticker = asyncio.create_task(self._tick_loop(), name="bot-tick") if self.monitor is not None else None
        stopper = asyncio.create_task(stop_event.wait(), name="bot-stop")
        try:
            await asyncio.wait({pump, stopper}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stopper.cancel()
            for f in feeds:
                stop = getattr(f, "stop", None)
                if callable(stop):
                    stop()
            if not pump.done():
                try:
                    await asyncio.wait_for(asyncio.shield(pump), self.execution_grace_s)
                except TimeoutError:
                    log.warning("feeds did not end within %.1fs of stop; cancelling", self.execution_grace_s)
                    pump.cancel()
                await asyncio.gather(pump, return_exceptions=True)
            if ticker is not None:
                ticker.cancel()
                await asyncio.gather(ticker, return_exceptions=True)
            await self._drain_executions()
            self._report_leftovers()
            await asyncio.gather(stopper, return_exceptions=True)
        if not pump.cancelled() and pump.exception() is not None:
            raise pump.exception()  # type: ignore[misc]

    async def _pump(self, feeds: Sequence[Feed]) -> None:
        merged = merge_feeds(feeds)
        try:
            async for ev in merged:
                try:
                    await self.handle_event(ev)
                except Exception:
                    # Keep consuming so exits keep running, but stop entering: a
                    # bug in event handling is not something to trade through.
                    log.exception("error handling %r", ev)
                    self.counters.errors += 1
                    self.trip(INTERNAL_ERROR)
        finally:
            aclose = getattr(merged, "aclose", None)
            if aclose is not None:
                await aclose()

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(self.tick_interval_s)
            try:
                await self.tick()
            except Exception:
                log.exception("error in periodic tick")
                self.counters.errors += 1
                self.trip(INTERNAL_ERROR)

    async def _drain_executions(self) -> None:
        tasks = [t for t in self._inflight.values() if not t.done()]
        if not tasks:
            return
        log.info("waiting for %d in-flight execution(s) to finish", len(tasks))
        _, pending = await asyncio.wait(tasks, timeout=self.execution_grace_s)
        for t in pending:
            log.error("%s still running after %.1fs; cancelling (order state may be unknown)",
                      t.get_name(), self.execution_grace_s)
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            self.alerter.send(f"arbbot [{self.label}] shutdown cancelled {len(pending)} running execution(s); "
                              "check open orders and balances on the venues.")

    def _report_leftovers(self) -> None:
        """Alert positions that are not flat, then journal the ``shutdown`` record that closes a run."""
        m = self.monitor
        left: dict[str, list[str]] = {
            "open": [p.id for p in m.positions] if m else [],
            "residual": [p.id for p in m.residuals] if m else [],
            "unresolved": [p.id for p in m.unresolved] if m else [],
        }
        if any(left.values()):
            self.alerter.send(
                f"arbbot [{self.label}] stopped with positions not flat: {left}. They are no longer managed."
            )
        dust = [p.id for p in m.dust] if m else []
        self._record("shutdown", {"positions": left, "dust_positions": dust, **self.counters.summary()})
