"""Hard risk limits: pre-trade checks, liquidity gate and kill switch.

Every signal passes ``RiskManager.check`` before an order is sent, and every
execution report comes back through ``on_execution``. Exits (stops, targets,
time stops, hedges) never go through ``check``: risk never blocks getting flat.

``check`` returns a ``RiskDecision``. Rejections carry one of these reason
codes (a contract with the bot, engine and journal), tested in this order:

  ``halted:<why>``                  kill switch tripped (``why`` = ``halt_reason``)
  ``rate_limit``                    ``max_trades_per_minute`` filled trades in the last 60 s
  ``no_quote:<venue>``              no quote in the book (or venue/instrument not configured)
  ``stale_quote:<venue>``           quote older than ``max_quote_age_ms``, or the venue's feed
                                    reported a disconnect (invariant 2)
  ``low_liquidity:<venue>``         liquidity gate closed, or current top depth below the floor
  ``edge_gone``                     cross-venue edge recomputed from the CURRENT quotes no longer
                                    clears ``min_net_edge_bps`` after fees + slippage
  ``max_open_positions``            REFERENCE_LAG entry while the position limit is reached
  ``exposure_limit``                no net-exposure headroom left for a tradable size
  ``insufficient_inventory:<venue>`` balance on that venue too small for a tradable size
  ``below_min_notional``            size (after all caps and lot flooring) under a venue minimum

Approved decisions carry ``reason="ok"`` and
``size = floor_lot(min(signal.size, max_order_notional / price, inventory per leg,
exposure headroom / price))``. When that size is zero or below a leg's
``min_notional``, the reason names the binding (smallest) cap: the exposure
headroom -> ``exposure_limit``, a leg's inventory -> ``insufficient_inventory:<venue>``,
otherwise ``below_min_notional``.

The min-notional check uses the price each leg's order will carry: a BUY
leg's limit is at or above the ask, a SELL leg's limit may be as low as
``bid * (1 - max_slippage_bps/1e4)``, and venues check the notional at the
limit price.

The kill switch trips on a RESIDUAL or UNKNOWN execution, on a realized UTC-day
loss of ``daily_loss_limit``, or on ``max_consecutive_hedge_failures`` FLATTENED
cross-venue arbs in a row (a partial exit of a directional position is a retry
of that exit, bounded by the monitor's ``max_exit_attempts``, not a hedge
failure). Only ``reset()`` (the operator) clears it.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass

from .clock import Clock
from .config import BotConfig, InstrumentConfig, VenueConfig
from .feeds.base import QuoteBook
from .mathutil import common_lot, edge_bps, floor_to_step
from .models import (
    ExecutionOutcome,
    ExecutionReport,
    FeedStatus,
    Leg,
    Quote,
    Side,
    Signal,
    SignalKind,
    split_symbol,
)
from .portfolio import Portfolio

log = logging.getLogger(__name__)

# Float timestamps carry ~0.2us of rounding at epoch scale; timer comparisons
# (liquidity recovery, rate window) tolerate 1us, matching the scanners.
_TIMER_EPS_S = 1e-6
_RATE_WINDOW_S = 60.0
_DAY_S = 86400.0

# Reason codes. Venue-specific ones are rendered as "<code>:<venue>".
APPROVED = "ok"
HALTED = "halted"
RATE_LIMIT = "rate_limit"
NO_QUOTE = "no_quote"
STALE_QUOTE = "stale_quote"
LOW_LIQUIDITY = "low_liquidity"
EDGE_GONE = "edge_gone"
MAX_OPEN_POSITIONS = "max_open_positions"
EXPOSURE_LIMIT = "exposure_limit"
INSUFFICIENT_INVENTORY = "insufficient_inventory"
BELOW_MIN_NOTIONAL = "below_min_notional"

# Kill-switch causes set automatically (``halt_reason``; check reports "halted:<cause>").
TRIP_RESIDUAL = "residual"
TRIP_UNKNOWN = "unknown"
TRIP_DAILY_LOSS = "daily_loss_limit"
TRIP_HEDGE_FAILURES = "consecutive_hedge_failures"

_RESETS_HEDGE_FAILURES = frozenset(
    {ExecutionOutcome.COMPLETED, ExecutionOutcome.OPENED, ExecutionOutcome.CLOSED}
)


@dataclass(frozen=True, slots=True)
class RiskDecision:
    approved: bool
    size: float  # approved base size; 0.0 when rejected
    reason: str  # "ok" when approved, otherwise a reason code (see module docstring)


def _reject(reason: str) -> RiskDecision:
    return RiskDecision(False, 0.0, reason)


def _utc_day(t: float) -> int:
    """Days since the epoch; POSIX time has exactly 86400 s per UTC day."""
    return int(t // _DAY_S)


@dataclass(slots=True)
class _Liquidity:
    """Gate state for one (venue, symbol). Unseen pairs are open."""

    blocked: bool = False
    recovering_since: float | None = None  # first time depth was back >= floor while blocked


@dataclass(frozen=True, slots=True)
class _LegView:
    leg: Leg
    venue: VenueConfig
    inst: InstrumentConfig
    quote: Quote  # current top of book for the leg

    @property
    def price(self) -> float:
        return self.quote.price_for(self.leg.side)


class RiskManager:
    """Pre-trade limits, liquidity/connectivity gate, PnL tracking and the kill switch."""

    def __init__(self, cfg: BotConfig, portfolio: Portfolio, clock: Clock) -> None:
        self._cfg = cfg
        self._risk = cfg.risk
        self._portfolio = portfolio
        self._clock = clock

        self._base_of: dict[str, str] = {s: split_symbol(s)[0] for s in cfg.symbols()}
        self._symbols_of: dict[str, tuple[str, ...]] = {}
        for sym, base in self._base_of.items():
            self._symbols_of[base] = (*self._symbols_of.get(base, ()), sym)
        self._dust: dict[str, float] = {}  # per base asset: smallest configured lot
        for v in cfg.venues:
            for inst in v.instruments:
                base = self._base_of[inst.symbol]
                self._dust[base] = min(self._dust.get(base, math.inf), inst.lot_size)

        self._liquidity: dict[tuple[str, str], _Liquidity] = {}
        self._disconnected: set[str] = set()
        self._last_mid: dict[str, float] = {}  # per base asset, fallback mark for exposure

        self._halt_reason: str | None = None
        self._day = _utc_day(clock.now())
        self._daily_pnl = 0.0
        self._hedge_failures = 0
        self._trade_times: deque[float] = deque()

    # ------------------------------------------------------------------ market state

    def on_quote(self, quote: Quote) -> None:
        """Liquidity gate: block at once when top depth < floor; re-open after it holds >= floor.

        An invalid quote (crossed, non-positive) counts as below the floor.
        Re-opening needs depth >= ``min_top_depth_notional`` on every update for
        ``liquidity_recovery_s`` (clock time); any dip restarts the timer.
        """
        now = self._clock.now()
        valid = quote.is_valid()
        base = self._base_of.get(quote.symbol)
        if valid and base is not None:
            self._last_mid[base] = quote.mid
        st = self._liquidity.setdefault((quote.venue, quote.symbol), _Liquidity())
        if not valid or quote.depth_notional() < self._risk.min_top_depth_notional:
            st.blocked = True
            st.recovering_since = None
        elif st.blocked:
            if st.recovering_since is None:
                st.recovering_since = now
            if self._recovered(st, now):
                st.blocked = False
                st.recovering_since = None

    def on_feed_status(self, status: FeedStatus) -> None:
        """A disconnected venue is untradable until it reconnects.

        A disconnect also restarts any liquidity recovery in progress on that
        venue: depth was not observed while the feed was down.
        """
        if status.connected:
            self._disconnected.discard(status.venue)
            return
        self._disconnected.add(status.venue)
        for (venue, _), st in self._liquidity.items():
            if venue == status.venue:
                st.recovering_since = None

    def tradable(self, venue: str, symbol: str) -> bool:
        """Venue connected and the (venue, symbol) liquidity gate open."""
        return venue not in self._disconnected and self._liquidity_open(venue, symbol, self._clock.now())

    def _recovered(self, st: _Liquidity, now: float) -> bool:
        return (
            st.recovering_since is not None
            and now - st.recovering_since >= self._risk.liquidity_recovery_s - _TIMER_EPS_S
        )

    def _liquidity_open(self, venue: str, symbol: str, now: float) -> bool:
        st = self._liquidity.get((venue, symbol))
        return st is None or not st.blocked or self._recovered(st, now)

    # ------------------------------------------------------------------ exposure

    def _mark(self, asset: str, book: QuoteBook) -> float | None:
        """Mean mid of every valid book quote on ``asset``; else the last mid seen in ``on_quote``."""
        mids = [
            q.mid
            for sym in self._symbols_of.get(asset, ())
            for q in book.quotes_for(sym).values()
            if q.is_valid()
        ]
        if mids:
            return sum(mids) / len(mids)
        return self._last_mid.get(asset)

    def net_exposure_notional(self, book: QuoteBook) -> float:
        """Sum over base assets of ``|portfolio.net_base_change(asset)| * mid``.

        An exposure of at least one lot that cannot be priced at all is
        unbounded risk: returns ``inf`` (which blocks new entries).
        """
        total = 0.0
        for asset, dust in self._dust.items():
            change = self._portfolio.net_base_change(asset)
            if change == 0.0:
                continue
            mid = self._mark(asset, book)
            if mid is None:
                if abs(change) < dust:
                    continue
                return math.inf
            total += abs(change) * mid
        return total

    # ------------------------------------------------------------------ pre-trade check

    def _instrument(self, venue: str, symbol: str) -> tuple[VenueConfig, InstrumentConfig] | None:
        try:
            v = self._cfg.venue(venue)
        except KeyError:
            return None
        inst = v.instrument(symbol)
        return None if inst is None else (v, inst)

    def check(self, signal: Signal, book: QuoteBook, *, open_positions: int = 0) -> RiskDecision:
        """Approve ``signal`` with a size, or reject it with a reason code (module docstring)."""
        now = self._clock.now()
        self._roll_day(now)
        # Limits are code checked on every signal: a day already past its loss
        # limit stays closed even if the operator resets before UTC midnight.
        if self._halt_reason is None and self._daily_pnl <= -self._risk.daily_loss_limit:
            self.trip(TRIP_DAILY_LOSS)
        if self._halt_reason is not None:
            return _reject(f"{HALTED}:{self._halt_reason}")
        if self._trades_in_window(now) >= self._risk.max_trades_per_minute:
            return _reject(RATE_LIMIT)
        if not signal.legs:
            return _reject(EDGE_GONE)  # malformed: nothing to trade

        legs: list[_LegView] = []
        for leg in signal.legs:
            found = self._instrument(leg.venue, leg.symbol)
            q = book.get(leg.venue, leg.symbol)
            if found is None or q is None:
                return _reject(f"{NO_QUOTE}:{leg.venue}")
            legs.append(_LegView(leg, found[0], found[1], q))

        max_age_s = self._risk.max_quote_age_ms / 1000.0
        for lv in legs:
            v = lv.leg.venue
            if v in self._disconnected or not lv.quote.is_valid() or lv.quote.age(now) > max_age_s:
                return _reject(f"{STALE_QUOTE}:{v}")

        floor = self._risk.min_top_depth_notional
        for lv in legs:
            v = lv.leg.venue
            if not self._liquidity_open(v, lv.leg.symbol, now) or lv.quote.depth_notional() < floor:
                return _reject(f"{LOW_LIQUIDITY}:{v}")

        if signal.kind is SignalKind.CROSS_VENUE and not self._edge_holds(legs):
            return _reject(EDGE_GONE)
        if signal.kind is SignalKind.REFERENCE_LAG and open_positions >= self._risk.max_open_positions:
            return _reject(MAX_OPEN_POSITIONS)
        return self._size(signal, legs, book)

    def _edge_holds(self, legs: list[_LegView]) -> bool:
        """Scanner formula on the current quotes: ``gross - (fee+slip on both legs) >= X`` and ``> 0``.

        A cross-venue signal that is not exactly one BUY and one SELL of the
        same symbol on two venues has no edge (invariant 1).
        """
        buys = [lv for lv in legs if lv.leg.side is Side.BUY]
        sells = [lv for lv in legs if lv.leg.side is Side.SELL]
        if len(legs) != 2 or len(buys) != 1 or len(sells) != 1:
            return False
        b, s = buys[0], sells[0]
        if b.leg.symbol != s.leg.symbol or b.leg.venue == s.leg.venue:
            return False
        gross = edge_bps(b.quote.ask, s.quote.bid)
        cost = b.venue.taker_fee_bps + b.venue.slippage_bps + s.venue.taker_fee_bps + s.venue.slippage_bps
        net = gross - cost
        return net >= self._cfg.signal.min_net_edge_bps and net > 0

    def _size(self, signal: Signal, legs: list[_LegView], book: QuoteBook) -> RiskDecision:
        """min(all caps) floored to the common lot; reject naming the binding cap if untradable.

        Notional caps use the entry price at the current quote: the BUY leg's
        ask for an arb (as the scanner sizes it), the single leg's price for a
        directional trade.
        """
        risk, ex = self._risk, self._cfg.execution
        entry = next((lv for lv in legs if lv.leg.side is Side.BUY), legs[0])
        price = entry.price
        headroom = risk.max_net_exposure_notional - self.net_exposure_notional(book)
        caps: list[tuple[float, str]] = [  # (base qty, reason if this cap binds an untradable size)
            (signal.size, BELOW_MIN_NOTIONAL),
            (risk.max_order_notional / price, BELOW_MIN_NOTIONAL),
            (headroom / price, EXPOSURE_LIMIT),
        ]
        for lv in legs:
            venue, symbol = lv.leg.venue, lv.leg.symbol
            if lv.leg.side is Side.BUY:
                limit_price = lv.quote.ask * (1 + ex.max_slippage_bps / 1e4)
                inventory = self._portfolio.buying_power(venue, symbol, limit_price, lv.venue.taker_fee_bps)
            else:
                inventory = self._portfolio.sellable(venue, symbol)
            caps.append((inventory, f"{INSUFFICIENT_INVENTORY}:{venue}"))

        raw = min(qty for qty, _ in caps)
        size = 0.0
        if raw > 0 and math.isfinite(raw):
            size = max(floor_to_step(raw, common_lot(*(lv.inst.lot_size for lv in legs))), 0.0)
        if size <= 0 or any(size * self._order_price(lv) < lv.inst.min_notional for lv in legs):
            return _reject(min(caps, key=lambda c: c[0])[1])  # first listed wins ties
        return RiskDecision(True, size, APPROVED)

    def _order_price(self, lv: _LegView) -> float:
        """Lowest limit price the leg's entry order can carry (venues check min notional at the limit)."""
        if lv.leg.side is Side.BUY:
            return lv.quote.ask  # the BUY limit is quantized down from ask * (1 + slippage): never below the ask
        return lv.quote.bid * (1 - self._cfg.execution.max_slippage_bps / 1e4)

    # ------------------------------------------------------------------ post-trade

    def on_execution(self, report: ExecutionReport) -> None:
        """Book realized PnL, track hedge failures and trade rate, and trip the kill switch."""
        now = self._clock.now()
        self._roll_day(now)
        self._daily_pnl += report.realized_pnl
        outcome = report.outcome
        if outcome is ExecutionOutcome.FLATTENED:
            if report.position_id is None:  # an arb's unequal fills, not a directional partial exit
                self._hedge_failures += 1
        elif outcome in _RESETS_HEDGE_FAILURES:
            self._hedge_failures = 0
        if any(o.filled_qty > 0 for o in report.orders):
            self._trade_times.append(now)
        self._trades_in_window(now)  # prune

        if outcome is ExecutionOutcome.RESIDUAL:
            self.trip(TRIP_RESIDUAL)
        elif outcome is ExecutionOutcome.UNKNOWN:
            self.trip(TRIP_UNKNOWN)
        if self._daily_pnl <= -self._risk.daily_loss_limit:
            self.trip(TRIP_DAILY_LOSS)
        if self._hedge_failures >= self._risk.max_consecutive_hedge_failures:
            self.trip(TRIP_HEDGE_FAILURES)

    def _roll_day(self, now: float) -> None:
        day = _utc_day(now)
        if day > self._day:
            self._day = day
            self._daily_pnl = 0.0

    def _trades_in_window(self, now: float) -> int:
        """Filled trades in the last 60 s; a trade exactly 60 s old has left the window."""
        times = self._trade_times
        while times and now - times[0] >= _RATE_WINDOW_S - _TIMER_EPS_S:
            times.popleft()
        return len(times)

    # ------------------------------------------------------------------ kill switch

    def trip(self, reason: str) -> None:
        """Halt all new entries. The first cause is kept; only ``reset()`` clears it."""
        reason = reason or "manual"
        if self._halt_reason is None:
            self._halt_reason = reason
            log.warning("kill switch tripped: %s", reason)
        else:
            log.warning("kill switch already tripped (%s); also: %s", self._halt_reason, reason)

    def reset(self) -> None:
        """Operator reset: clears the halt and the hedge-failure streak (not the day's PnL)."""
        if self._halt_reason is not None:
            log.warning("kill switch reset (was: %s)", self._halt_reason)
        self._halt_reason = None
        self._hedge_failures = 0

    @property
    def halted(self) -> bool:
        return self._halt_reason is not None

    @property
    def halt_reason(self) -> str | None:
        return self._halt_reason

    @property
    def daily_pnl(self) -> float:
        """Realized PnL of the current UTC day (by the injected clock)."""
        self._roll_day(self._clock.now())
        return self._daily_pnl

    @property
    def consecutive_hedge_failures(self) -> int:
        return self._hedge_failures

    @property
    def trades_last_minute(self) -> int:
        return self._trades_in_window(self._clock.now())
