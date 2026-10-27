"""Mispricing logic: cross-venue arbitrage and reference-lag signals.

Both scanners are driven per quote update and read everything else from the
``QuoteBook`` and ``Portfolio``; time comes only from the injected ``Clock``.

``CrossVenueScanner`` pairs the updated venue with every other venue listing
the SAME canonical symbol (BTC-USD is never paired with BTC-USDT), in both
directions, and emits at most one signal per update: the best net edge after
taker fees and expected slippage on both legs, provided it clears
``signal.min_net_edge_bps`` (X), has a tradable size, has persisted for
``persistence_ms`` and is not cooling down.

``ReferenceLagScanner`` tracks the normal premium of a target venue over a
reference venue with a time-decayed EMA and trades the target when its quote
strays from the basis-adjusted fair value by more than round-trip costs plus a
threshold. Each target quote is evaluated against the basis as it stood
BEFORE that quote, then folded in, so a sudden dislocation cannot dilute the
fair value it is measured against. Its edge is measured to the take-profit
target the position aims for (``take_profit_fraction`` of the gap to fair),
not to fair value itself.

Warm-up: an observation stamped at the same time as the previous one carries
no EMA weight and is not counted. When ``min_basis_samples`` observations
have been folded, the basis is re-seeded with their median: the EMA starts
from its first observation with full weight, and with a half-life of minutes
it would still be almost entirely that one (possibly transient) premium.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from .clock import Clock
from .config import BotConfig, InstrumentConfig, VenueConfig
from .feeds.base import QuoteBook
from .mathutil import common_lot, edge_bps, floor_to_step
from .models import Leg, Quote, Side, Signal, SignalKind, next_id
from .portfolio import Portfolio

# Float timestamps carry ~0.2us of rounding at epoch scale; timer comparisons
# (persistence, cooldown) tolerate 1us so a boundary like t0 + 0.2s fires.
_TIMER_EPS_S = 1e-6

PairKey = tuple[str, str, str]  # (symbol, buy venue, sell venue)


# --------------------------------------------------------------------------- stats


@dataclass(slots=True)
class EdgeHistogram:
    """Fixed-bin histogram of edges in bps: ``[lo, hi)`` in ``width`` bins plus under/overflow."""

    lo: float = -50.0
    hi: float = 50.0
    width: float = 5.0
    counts: list[int] = field(init=False)
    underflow: int = 0
    overflow: int = 0

    def __post_init__(self) -> None:
        if self.width <= 0 or self.hi <= self.lo:
            raise ValueError("EdgeHistogram needs width > 0 and hi > lo")
        self.counts = [0] * math.ceil((self.hi - self.lo) / self.width - 1e-9)

    def add(self, x: float) -> None:
        if x < self.lo:
            self.underflow += 1
            return
        i = math.floor((x - self.lo) / self.width)
        if x >= self.hi or i >= len(self.counts):
            self.overflow += 1
        else:
            self.counts[i] += 1

    @property
    def total(self) -> int:
        return self.underflow + sum(self.counts) + self.overflow

    def summary(self) -> dict[str, int]:
        """Ordered ``{label: count}`` for every bin, e.g. ``{"<-50": 0, "[-50,-45)": 2, ..., ">=50": 0}``."""
        out = {f"<{self.lo:g}": self.underflow}
        for i, c in enumerate(self.counts):
            a = self.lo + i * self.width
            b = min(a + self.width, self.hi)
            out[f"[{a:g},{b:g})"] = c
        out[f">={self.hi:g}"] = self.overflow
        return out


@dataclass(slots=True)
class ScannerStats:
    """Counters and edge histograms for tuning the threshold X.

    ``evaluations`` counts pair evaluations whose edge was computed (both
    quotes usable). ``candidates`` counts evaluations that cleared costs + X
    with a tradable size. ``emitted`` counts signals returned. ``updates``
    counts quote updates with at least one evaluation; for each of those the
    BEST gross and best net edge among the evaluated pairs go into the
    histograms. ``rejects`` counts why evaluations did not become signals.
    """

    updates: int = 0
    evaluations: int = 0
    candidates: int = 0
    emitted: int = 0
    rejects: dict[str, int] = field(default_factory=dict)
    gross_hist: EdgeHistogram = field(default_factory=EdgeHistogram)
    net_hist: EdgeHistogram = field(default_factory=EdgeHistogram)
    best_gross_bps: float | None = None
    best_net_bps: float | None = None

    def reject(self, reason: str) -> None:
        self.rejects[reason] = self.rejects.get(reason, 0) + 1

    def observe(self, gross: float, net: float) -> None:
        """Record the best gross / net edge of one quote update."""
        self.updates += 1
        self.gross_hist.add(gross)
        self.net_hist.add(net)
        self.best_gross_bps = gross if self.best_gross_bps is None else max(self.best_gross_bps, gross)
        self.best_net_bps = net if self.best_net_bps is None else max(self.best_net_bps, net)

    def summary(self) -> dict[str, object]:
        return {
            "updates": self.updates,
            "evaluations": self.evaluations,
            "candidates": self.candidates,
            "emitted": self.emitted,
            "rejects": dict(sorted(self.rejects.items())),
            "best_gross_bps": self.best_gross_bps,
            "best_net_bps": self.best_net_bps,
            "gross_edge_bps": self.gross_hist.summary(),
            "net_edge_bps": self.net_hist.summary(),
        }


# --------------------------------------------------------------------------- helpers


def _usable_reason(q: Quote, now: float, max_age_s: float) -> str | None:
    """None if ``q`` can be traded on; otherwise "invalid" or "stale"."""
    if not q.is_valid():
        return "invalid"
    if q.age(now) > max_age_s:
        return "stale"
    return None


def _superseded(quote: Quote, current: Quote | None) -> bool:
    """True when the book already holds a newer quote for this venue/symbol than ``quote``.

    Guards against a caller passing an update the book rejected (out of order).
    """
    if current is None or current == quote:
        return False
    if current.seq is not None and quote.seq is not None:
        return current.seq >= quote.seq
    return current.ts_local > quote.ts_local


def _floored_size(raw: float, caps: Iterable[float], lot: float) -> float:
    size = min([raw, *caps])
    if size <= 0 or not math.isfinite(size):
        return 0.0
    return max(floor_to_step(size, lot), 0.0)


@dataclass(slots=True)
class _Assessment:
    signal: Signal | None
    reason: str  # "" when signal is set
    gross: float | None = None
    net: float | None = None


# --------------------------------------------------------------------------- cross venue


class CrossVenueScanner:
    """Same-symbol, two-venue taker arbitrage: buy the ask on one venue, sell the bid on another."""

    def __init__(self, cfg: BotConfig, clock: Clock, *, stats: ScannerStats | None = None,
                 ids: Callable[[str], str] | None = None) -> None:
        self._cfg = cfg
        self._clock = clock
        self.stats = stats if stats is not None else ScannerStats()
        self._next_id = ids or next_id
        self._qualified_since: dict[PairKey, float] = {}
        self._cooldown_until: dict[PairKey, float] = {}

    # ---- pure math

    def evaluate_pair(self, buy_q: Quote, sell_q: Quote, portfolio: Portfolio) -> Signal | None:
        """Signal for buying ``buy_q.ask`` and selling ``sell_q.bid`` now, or None. No timers, no stats."""
        return self._assess(buy_q, sell_q, portfolio, self._clock.now()).signal

    def _instrument(self, venue: str, symbol: str) -> tuple[VenueConfig, InstrumentConfig] | None:
        try:
            v = self._cfg.venue(venue)
        except KeyError:
            return None
        inst = v.instrument(symbol)
        return None if inst is None else (v, inst)

    def _assess(self, buy_q: Quote, sell_q: Quote, portfolio: Portfolio, now: float) -> _Assessment:
        if buy_q.symbol != sell_q.symbol:
            return _Assessment(None, "symbol_mismatch")
        if buy_q.venue == sell_q.venue:
            return _Assessment(None, "same_venue")
        max_age_s = self._cfg.risk.max_quote_age_ms / 1000.0
        for q in (buy_q, sell_q):
            why = _usable_reason(q, now, max_age_s)
            if why is not None:
                return _Assessment(None, why)
        symbol = buy_q.symbol
        b = self._instrument(buy_q.venue, symbol)
        s = self._instrument(sell_q.venue, symbol)
        if b is None or s is None:
            return _Assessment(None, "unconfigured")
        (bv, bi), (sv, si) = b, s

        ask, bid = buy_q.ask, sell_q.bid
        gross = edge_bps(ask, bid)
        buy_cost_bps = bv.taker_fee_bps + bv.slippage_bps
        sell_cost_bps = sv.taker_fee_bps + sv.slippage_bps
        cost = buy_cost_bps + sell_cost_bps
        net = gross - cost
        if not (net >= self._cfg.signal.min_net_edge_bps and net > 0):
            return _Assessment(None, "below_threshold", gross, net)

        ex = self._cfg.execution
        size = _floored_size(
            self._cfg.signal.participation * min(buy_q.ask_size, sell_q.bid_size),
            (
                self._cfg.risk.max_order_notional / ask,
                portfolio.buying_power(buy_q.venue, symbol, ask * (1 + ex.max_slippage_bps / 1e4), bv.taker_fee_bps),
                portfolio.sellable(sell_q.venue, symbol),
            ),
            common_lot(bi.lot_size, si.lot_size),
        )
        if size <= 0:
            return _Assessment(None, "no_size", gross, net)
        if size * ask < bi.min_notional or size * bid < si.min_notional:
            return _Assessment(None, "min_notional", gross, net)

        expected_pnl = size * (bid * (1 - sell_cost_bps / 1e4) - ask * (1 + buy_cost_bps / 1e4))
        sig = Signal(
            id=self._next_id("sig"),
            kind=SignalKind.CROSS_VENUE,
            symbol=symbol,
            market=f"{symbol} buy@{buy_q.venue} sell@{sell_q.venue}",
            legs=(
                Leg(buy_q.venue, symbol, Side.BUY, ask, buy_q.ask_size),
                Leg(sell_q.venue, symbol, Side.SELL, bid, sell_q.bid_size),
            ),
            size=size,
            gross_edge_bps=gross,
            cost_bps=cost,
            net_edge_bps=net,
            expected_pnl=expected_pnl,
            entry=ask,
            stop=ask * (1 - ex.unwind_slippage_bps / 1e4),
            target=bid,
            ts=now,
        )
        return _Assessment(sig, "", gross, net)

    # ---- driven per update

    def on_quote(self, quote: Quote, book: QuoteBook, portfolio: Portfolio) -> list[Signal]:
        """Evaluate every pair involving ``quote.venue`` for ``quote.symbol``; at most one signal.

        ``quote`` is taken as that venue's current top of book (the caller
        stores it in ``book`` first); counterparties come from ``book``.
        """
        symbol = quote.symbol
        venues = [v.name for v in self._cfg.venues_for(symbol)]
        if quote.venue not in venues:
            return []
        if _superseded(quote, book.get(quote.venue, symbol)):
            self.stats.reject("superseded")
            return []
        now = self._clock.now()
        stats = self.stats

        eligible: list[Signal] = []
        best_gross: float | None = None
        best_net: float | None = None
        for other in venues:
            if other == quote.venue:
                continue
            other_q = book.get(other, symbol)
            for buy_q, sell_q in ((quote, other_q), (other_q, quote)):
                buy_venue = quote.venue if buy_q is quote else other
                sell_venue = other if buy_q is quote else quote.venue
                key = (symbol, buy_venue, sell_venue)
                if buy_q is None or sell_q is None:
                    self._qualified_since.pop(key, None)
                    stats.reject("no_quote")
                    continue
                res = self._assess(buy_q, sell_q, portfolio, now)
                if res.gross is not None and res.net is not None:
                    stats.evaluations += 1
                    best_gross = res.gross if best_gross is None else max(best_gross, res.gross)
                    best_net = res.net if best_net is None else max(best_net, res.net)
                if res.signal is None:
                    self._qualified_since.pop(key, None)
                    stats.reject(res.reason)
                    continue
                stats.candidates += 1
                since = self._qualified_since.setdefault(key, now)
                if now < self._cooldown_until.get(key, -math.inf) - _TIMER_EPS_S:
                    stats.reject("cooldown")
                elif now - since < self._cfg.signal.persistence_ms / 1000.0 - _TIMER_EPS_S:
                    stats.reject("persistence")
                else:
                    eligible.append(res.signal)

        if best_gross is not None and best_net is not None:
            stats.observe(best_gross, best_net)
        if not eligible:
            return []
        best = max(eligible, key=lambda sg: sg.net_edge_bps)  # first wins ties: config order
        buy_leg, sell_leg = best.legs
        self._cooldown_until[(symbol, buy_leg.venue, sell_leg.venue)] = now + self._cfg.signal.cooldown_ms / 1000.0
        stats.emitted += 1
        return [best]


# --------------------------------------------------------------------------- reference lag


class ReferenceLagScanner:
    """Directional trade on a venue that lags a reference venue, around an EMA basis."""

    def __init__(self, cfg: BotConfig, clock: Clock, *, stats: ScannerStats | None = None,
                 ids: Callable[[str], str] | None = None) -> None:
        self._cfg = cfg
        self._lag = cfg.reference_lag
        self._clock = clock
        self.stats = stats if stats is not None else ScannerStats()
        self._next_id = ids or next_id
        self._basis: float | None = None
        self._last_fold_ts: float | None = None
        self._samples = 0
        self._warmup: list[float] | None = []  # premiums folded during warm-up; None once warm
        self._cooldown_until = -math.inf

    @property
    def basis_bps(self) -> float | None:
        """EMA of ``(mid_target - mid_ref) / mid_ref`` in bps; None before the first sample."""
        return self._basis

    @property
    def samples(self) -> int:
        """Weighted observations folded into the basis so far (same-time repeats are not counted)."""
        return self._samples

    @property
    def warm(self) -> bool:
        """True once ``min_basis_samples`` observations re-seeded the basis with their median."""
        return self._warmup is None

    def _fold(self, premium_bps: float, now: float) -> None:
        if self._basis is None or self._last_fold_ts is None:
            self._basis = premium_bps
        else:
            dt = now - self._last_fold_ts
            if dt <= 0:
                return  # no time has passed: zero EMA weight, so not a sample either
            alpha = 1.0 - math.exp(-math.log(2.0) * dt / self._lag.basis_halflife_s)
            self._basis += alpha * (premium_bps - self._basis)
        self._last_fold_ts = now
        self._samples += 1
        if self._warmup is not None:
            self._warmup.append(premium_bps)
            if self._samples >= self._lag.min_basis_samples:
                # Robust seed: no single early observation dominates the slow EMA from here on.
                self._basis = statistics.median(self._warmup)
                self._warmup = None

    def on_quote(self, quote: Quote, book: QuoteBook, portfolio: Portfolio) -> list[Signal]:
        """Evaluate on target or reference updates; fold only target observations into the basis.

        A target quote is first evaluated against the current basis, then
        folded in. A reference quote re-evaluates the target's standing quote
        against the moved reference (the lag this strategy trades) without
        touching the basis.
        """
        lag = self._lag
        if not lag.enabled:
            return []
        is_target = quote.venue == lag.target_venue and quote.symbol == lag.target_symbol
        is_ref = quote.venue == lag.reference_venue and quote.symbol == lag.reference_symbol
        if not (is_target or is_ref):
            return []
        if _superseded(quote, book.get(quote.venue, quote.symbol)):
            self.stats.reject("superseded")
            return []
        if is_target:
            target_q, ref_q = quote, book.get(lag.reference_venue, lag.reference_symbol)
        else:
            target_q, ref_q = book.get(lag.target_venue, lag.target_symbol), quote
        if target_q is None or ref_q is None:
            self.stats.reject("no_quote")
            return []
        now = self._clock.now()
        max_age_s = self._cfg.risk.max_quote_age_ms / 1000.0
        for q in (target_q, ref_q):
            why = _usable_reason(q, now, max_age_s)
            if why is not None:
                self.stats.reject(why)
                return []

        out: list[Signal] = []
        if self._basis is not None and self.warm:
            sig = self._evaluate(target_q, ref_q, self._basis, portfolio, now)
            if sig is not None:
                if now < self._cooldown_until - _TIMER_EPS_S:
                    self.stats.reject("cooldown")
                else:
                    self._cooldown_until = now + self._cfg.signal.cooldown_ms / 1000.0
                    self.stats.emitted += 1
                    out.append(sig)
        else:
            self.stats.reject("warmup")
        if is_target:
            self._fold((target_q.mid - ref_q.mid) / ref_q.mid * 1e4, now)
        return out

    def _evaluate(self, tq: Quote, rq: Quote, basis_bps: float, portfolio: Portfolio, now: float) -> Signal | None:
        lag, stats = self._lag, self.stats
        try:
            venue = self._cfg.venue(lag.target_venue)
        except KeyError:
            stats.reject("unconfigured")
            return None
        inst = venue.instrument(lag.target_symbol)
        if inst is None:
            stats.reject("unconfigured")
            return None

        fair = rq.mid * (1 + basis_bps / 1e4)
        leg_cost_bps = venue.taker_fee_bps + venue.slippage_bps
        cost = 2 * leg_cost_bps
        tp = lag.take_profit_fraction
        buy_gap = (fair - tq.ask) / tq.ask * 1e4
        sell_gap = (tq.bid - fair) / tq.bid * 1e4
        stats.evaluations += 1
        best_edge = tp * max(buy_gap, sell_gap)  # entry to take-profit target, in bps of the entry
        stats.observe(best_edge, best_edge - cost)

        if tq.ask < fair:
            side, gap, price, displayed = Side.BUY, buy_gap, tq.ask, tq.ask_size
        elif tq.bid > fair:
            side, gap, price, displayed = Side.SELL, sell_gap, tq.bid, tq.bid_size
        else:
            stats.reject("below_threshold")
            return None
        # The trade aims for ``target``, ``tp`` of the way to fair: that is its edge, not the full gap.
        gross = tp * gap
        net = gross - cost
        if not (net >= lag.entry_threshold_bps and net > 0):
            stats.reject("below_threshold")
            return None

        c = leg_cost_bps / 1e4
        if side is Side.BUY:
            target = price + tp * (fair - price)
            stop = price * (1 - lag.stop_bps / 1e4)
            inventory = portfolio.buying_power(
                lag.target_venue, lag.target_symbol,
                price * (1 + self._cfg.execution.max_slippage_bps / 1e4), venue.taker_fee_bps,
            )
        else:
            target = price - tp * (price - fair)
            stop = price * (1 + lag.stop_bps / 1e4)
            inventory = portfolio.sellable(lag.target_venue, lag.target_symbol)
        size = _floored_size(
            self._cfg.signal.participation * displayed,
            (self._cfg.risk.max_order_notional / price, inventory),
            inst.lot_size,
        )
        if size <= 0:
            stats.reject("no_size")
            return None
        if size * price < inst.min_notional:
            stats.reject("min_notional")
            return None
        if side is Side.BUY:
            expected_pnl = size * (target * (1 - c) - price * (1 + c))
        else:
            expected_pnl = size * (price * (1 - c) - target * (1 + c))
        if expected_pnl <= 0:  # take-profit too small to cover the round trip
            stats.reject("unprofitable_target")
            return None
        stats.candidates += 1
        return Signal(
            id=self._next_id("sig"),
            kind=SignalKind.REFERENCE_LAG,
            symbol=lag.target_symbol,
            market=(
                f"{lag.target_symbol} {side.value}@{lag.target_venue} "
                f"ref {lag.reference_symbol}@{lag.reference_venue}"
            ),
            legs=(Leg(lag.target_venue, lag.target_symbol, side, price, displayed),),
            size=size,
            gross_edge_bps=gross,
            cost_bps=cost,
            net_edge_bps=net,
            expected_pnl=expected_pnl,
            entry=price,
            stop=stop,
            target=target,
            ts=now,
            max_hold_s=lag.max_hold_s,
        )
