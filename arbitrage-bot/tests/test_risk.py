"""Tests for arbbot.risk: pre-trade checks, liquidity gate, PnL tracking and the kill switch.

Expected numbers are worked out by hand in each test (fees, slippage, caps,
lot flooring, marks), never by calling the code under test. Signals are built
directly from ``models.Signal`` so these tests do not depend on the scanner.

Default world: venues A and B, BTC-USDT, taker fee 10 bps + slippage 1 bps per
leg (cost 22 bps), X = 5 bps, lot 0.001, min notional 5. Market: A 99.99/100.00,
B 100.30/100.31, 50 BTC a side (depth ~5000 >= 2000 floor). Risk: max order 500,
max net exposure 1000, recovery 5 s, quotes stale after 1.5 s, daily loss 50,
3 hedge failures, 20 trades/min. Execution max slippage 5 bps.
"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

from arbbot.clock import SimClock
from arbbot.config import (
    BotConfig,
    ExecutionConfig,
    InstrumentConfig,
    RiskConfig,
    SignalConfig,
    VenueConfig,
    validate,
)
from arbbot.feeds.base import QuoteBook
from arbbot.models import (
    ExecutionOutcome,
    ExecutionReport,
    FeedStatus,
    Leg,
    OrderResult,
    OrderStatus,
    Quote,
    Side,
    Signal,
    SignalKind,
)
from arbbot.portfolio import Portfolio
from arbbot.risk import RiskDecision, RiskManager

SYM = "BTC-USDT"
T0 = 1000.0


# --------------------------------------------------------------------------- fixtures


def venue(name: str, *, fee: float = 10.0, slip: float = 1.0, lot: float = 0.001,
          min_notional: float = 5.0) -> VenueConfig:
    return VenueConfig(
        name=name,
        feed="binance",
        taker_fee_bps=fee,
        slippage_bps=slip,
        instruments=(InstrumentConfig(symbol=SYM, venue_symbol="BTCUSDT", tick_size=0.01, lot_size=lot,
                                      min_notional=min_notional),),
    )


def make_cfg(*venues: VenueConfig, min_net_edge_bps: float = 5.0, **risk_kw: float) -> BotConfig:
    risk = RiskConfig(
        max_order_notional=500.0,
        max_net_exposure_notional=1000.0,
        max_open_positions=1,
        min_top_depth_notional=2000.0,
        liquidity_recovery_s=5.0,
        max_quote_age_ms=1500.0,
        daily_loss_limit=50.0,
        max_consecutive_hedge_failures=3,
        max_trades_per_minute=20,
    )
    cfg = BotConfig(
        venues=venues or (venue("A"), venue("B")),
        signal=SignalConfig(min_net_edge_bps=min_net_edge_bps),
        risk=replace(risk, **risk_kw),
        execution=ExecutionConfig(max_slippage_bps=5.0, unwind_slippage_bps=50.0),
    )
    validate(cfg)
    return cfg


def rich(usdt: float = 1_000_000.0, btc: float = 100.0) -> dict[str, dict[str, float]]:
    return {"A": {"USDT": usdt, "BTC": btc}, "B": {"USDT": usdt, "BTC": btc}}


def xsig(*, buy: str = "A", sell: str = "B", ask: float = 100.0, bid: float = 100.30, size: float = 2.0) -> Signal:
    """Cross-venue signal as the scanner would have emitted it at (ask, bid)."""
    gross = (bid - ask) / ask * 1e4
    return Signal(
        id="sig-x",
        kind=SignalKind.CROSS_VENUE,
        symbol=SYM,
        market=f"{SYM} buy@{buy} sell@{sell}",
        legs=(Leg(buy, SYM, Side.BUY, ask, 50.0), Leg(sell, SYM, Side.SELL, bid, 50.0)),
        size=size,
        gross_edge_bps=gross,
        cost_bps=22.0,
        net_edge_bps=gross - 22.0,
        expected_pnl=1.0,
        entry=ask,
        stop=ask * (1 - 50 / 1e4),
        target=bid,
        ts=0.0,
    )


def lagsig(*, venue_name: str = "A", side: Side = Side.BUY, price: float = 100.0, size: float = 1.5) -> Signal:
    sign = 1 if side is Side.BUY else -1
    return Signal(
        id="sig-lag",
        kind=SignalKind.REFERENCE_LAG,
        symbol=SYM,
        market=f"{SYM} {side.value}@{venue_name} ref {SYM}@B",
        legs=(Leg(venue_name, SYM, side, price, 50.0),),
        size=size,
        gross_edge_bps=40.0,
        cost_bps=22.0,
        net_edge_bps=18.0,
        expected_pnl=1.0,
        entry=price,
        stop=price * (1 - sign * 15 / 1e4),
        target=price * (1 + sign * 30 / 1e4),
        ts=0.0,
        max_hold_s=30.0,
    )


def report(outcome: ExecutionOutcome, *, pnl: float = 0.0, filled: float = 1.0,
           status: OrderStatus | None = None) -> ExecutionReport:
    if status is None:
        status = OrderStatus.FILLED if filled > 0 else OrderStatus.EXPIRED
    order = OrderResult(client_id="c-1", venue="A", symbol=SYM, side=Side.BUY, requested_qty=1.0,
                        filled_qty=filled, avg_price=100.0 if filled > 0 else 0.0, fee=0.0, status=status, ts=0.0)
    return ExecutionReport(signal_id="sig-x", outcome=outcome, orders=[order], realized_pnl=pnl)


class World:
    """Clock + config + portfolio + book + RiskManager, with quotes routed like the Bot does."""

    def __init__(self, cfg: BotConfig | None = None, balances: dict[str, dict[str, float]] | None = None,
                 *, start: float = T0) -> None:
        self.clock = SimClock(start)
        self.cfg = cfg if cfg is not None else make_cfg()
        self.pf = Portfolio(balances if balances is not None else rich())
        self.book = QuoteBook()
        self.risk = RiskManager(self.cfg, self.pf, self.clock)

    def at(self, t: float) -> World:
        self.clock.set(t)
        return self

    def quote(self, venue_name: str, bid: float, ask: float, *, size: float = 50.0) -> Quote:
        quote = Quote(venue=venue_name, symbol=SYM, bid=bid, bid_size=size, ask=ask, ask_size=size,
                      ts_local=self.clock.now())
        self.book.update(quote)
        self.risk.on_quote(quote)
        return quote

    def thick(self, venue_name: str = "A") -> Quote:
        return self.quote(venue_name, 99.99, 100.0) if venue_name == "A" else self.quote(venue_name, 100.30, 100.31)

    def thin(self, venue_name: str = "A") -> Quote:
        # 10 BTC a side: depth = min(99.99*10, 100*10) = 999.9 on A, 1003.0 on B; both < 2000
        if venue_name == "A":
            return self.quote(venue_name, 99.99, 100.0, size=10.0)
        return self.quote(venue_name, 100.30, 100.31, size=10.0)

    def market(self, a: tuple[float, float] = (99.99, 100.0), b: tuple[float, float] = (100.30, 100.31)) -> None:
        self.quote("A", *a)
        self.quote("B", *b)

    def check(self, sig: Signal, **kw: int) -> RiskDecision:
        return self.risk.check(sig, self.book, **kw)


def ok(size: float) -> RiskDecision:
    return RiskDecision(True, size, "ok")


def no(reason: str) -> RiskDecision:
    return RiskDecision(False, 0.0, reason)


# --------------------------------------------------------------------------- decision type


def test_risk_decision_is_a_frozen_value():
    d = RiskDecision(True, 1.5, "ok")
    assert (d.approved, d.size, d.reason) == (True, 1.5, "ok")
    with pytest.raises(FrozenInstanceError):
        d.size = 2.0  # type: ignore[misc]


def test_approves_a_clean_cross_venue_signal_at_its_size():
    w = World()
    w.market()
    assert w.check(xsig(size=2.0)) == ok(2.0)
    assert w.risk.tradable("A", SYM) and w.risk.tradable("B", SYM)


# --------------------------------------------------------------------------- sizing: min of all caps, floored


@pytest.mark.parametrize(
    ("risk_kw", "balances", "size", "expected"),
    [
        # signal size binds: caps are 500/100 = 5, exposure 1000/100 = 10, inventory huge
        ({}, rich(), 2.0, 2.0),
        # max_order_notional binds: 333.3333 / 100 = 3.333333 -> floor 0.001 -> 3.333
        ({"max_order_notional": 333.3333}, rich(), 4.0, 3.333),
        # buy-venue cash binds: 250 / (100 * 1.0005 * 1.001) = 250 / 100.15005 = 2.49625... -> 2.496
        ({}, {"A": {"USDT": 250.0, "BTC": 100.0}, "B": {"USDT": 1e6, "BTC": 100.0}}, 4.0, 2.496),
        # sell-venue base binds: 1.2345 BTC sellable on B -> 1.234
        ({}, {"A": {"USDT": 1e6, "BTC": 100.0}, "B": {"USDT": 1e6, "BTC": 1.2345}}, 4.0, 1.234),
    ],
    ids=["signal_size", "max_order_notional", "buy_inventory", "sell_inventory"],
)
def test_approved_size_is_min_of_caps_floored_to_lot(risk_kw, balances, size, expected):
    w = World(make_cfg(**risk_kw), balances)
    w.market()
    d = w.check(xsig(size=size))
    assert d.approved and d.reason == "ok"
    assert d.size == pytest.approx(expected, abs=1e-12)


def test_exposure_headroom_includes_existing_net_exposure_from_portfolio():
    w = World()
    w.market()
    # An earlier unhedged buy left +7 BTC. Mark = mean of book mids = (99.995 + 100.305) / 2 = 100.15.
    w.pf.apply_fill("A", SYM, Side.BUY, 7.0, 100.0, 0.0)
    assert w.risk.net_exposure_notional(w.book) == pytest.approx(7 * 100.15)
    # headroom = 1000 - 701.05 = 298.95 -> / 100 = 2.9895 -> floor 0.001 -> 2.989 (< 4.0 and < 5.0)
    d = w.check(xsig(size=4.0))
    assert d.approved
    assert d.size == pytest.approx(2.989, abs=1e-12)


def test_size_is_floored_to_the_common_lot_of_both_venues():
    w = World(make_cfg(venue("A", lot=0.002), venue("B", lot=0.003)))
    w.market()
    # lcm(0.002, 0.003) = 0.006; 1.0 -> 166 * 0.006 = 0.996 (on both grids)
    d = w.check(xsig(size=1.0))
    assert d.approved
    assert d.size == pytest.approx(0.996, abs=1e-12)


def test_reference_lag_caps_use_the_current_price_of_the_leg_side():
    w = World()
    w.quote("A", 99.0, 100.0)  # wide book: BUY pays 100, SELL receives 99; depth min(4950, 5000)
    # BUY: min(10, 500/100 = 5, cash huge, 1000/100 = 10) -> 5.0
    assert w.check(lagsig(side=Side.BUY, price=100.0, size=10.0)) == ok(5.0)
    # SELL: min(10, 500/99 = 5.0505..., 100 BTC, 1000/99 = 10.1) -> floor 0.001 -> 5.05
    d = w.check(lagsig(side=Side.SELL, price=99.0, size=10.0))
    assert d.approved
    assert d.size == pytest.approx(5.05, abs=1e-12)


# --------------------------------------------------------------------------- reason codes: market data


def test_no_quote_when_a_leg_has_no_quote_or_is_not_configured():
    w = World()
    w.quote("A", 99.99, 100.0)
    assert w.check(xsig()) == no("no_quote:B")
    w.quote("B", 100.30, 100.31)
    assert w.check(xsig(sell="C")) == no("no_quote:C")  # venue C is not configured


def test_stale_quote_after_max_quote_age():
    w = World()
    w.market()  # both at T0
    w.at(T0 + 1.5)  # age exactly 1.5 s == max_quote_age_ms: still fresh
    assert w.check(xsig()) == ok(2.0)
    w.at(T0 + 1.6)
    w.thick("A")  # A refreshed, B now 1.6 s old
    assert w.check(xsig()) == no("stale_quote:B")


def test_low_liquidity_when_top_of_book_is_thin():
    w = World()
    w.thick("A")
    w.thin("B")
    assert w.check(xsig()) == no("low_liquidity:B")
    assert not w.risk.tradable("B", SYM)


# --------------------------------------------------------------------------- reason codes: edge recheck


def test_edge_gone_when_current_quotes_no_longer_clear_costs():
    w = World()
    # The signal fired at bid 100.30 (net ~8 bps). B's bid is now 100.25:
    # gross = 0.25 / 100 * 1e4 = 25 bps exactly, costs 10+1+10+1 = 22 -> net 3 < X = 5.
    w.market(b=(100.25, 100.26))
    assert w.check(xsig(bid=100.30)) == no("edge_gone")


def test_edge_gone_when_buy_side_ask_moved_up():
    w = World()
    # gross = (100.30 - 100.10) / 100.10 * 1e4 = 19.98 bps -> net -2.02
    w.market(a=(99.99, 100.10))
    assert w.check(xsig(ask=100.0)) == no("edge_gone")


def test_edge_recheck_uses_current_quotes_not_the_signal_fields():
    w = World()
    # favorable move: the signal said bid 100.30, the book now pays 100.50 (gross 50, net 28)
    w.market(b=(100.50, 100.51))
    assert w.check(xsig(bid=100.30)) == ok(2.0)
    # a signal that claimed a huge edge is still rejected if the current book has none
    w.market(b=(100.25, 100.26))
    assert w.check(xsig(bid=101.0)) == no("edge_gone")


def test_edge_recheck_exact_boundary_counts_fees_and_slippage_on_both_legs():
    # gross is exactly 25 bps: ask 100, bid 100.25
    # fee 9 + slip 1 on both legs: cost 20 -> net 5.0 == X -> still clears
    w = World(make_cfg(venue("A", fee=9.0), venue("B", fee=9.0)))
    w.market(b=(100.25, 100.26))
    assert w.check(xsig(bid=100.25)) == ok(2.0)

    # buy-venue slippage 1.25: cost 20.25 -> net 4.75 < 5
    w = World(make_cfg(venue("A", fee=9.0, slip=1.25), venue("B", fee=9.0)))
    w.market(b=(100.25, 100.26))
    assert w.check(xsig(bid=100.25)) == no("edge_gone")

    # same costs (20) but X = 5.25 -> net 5.0 < 5.25
    w = World(make_cfg(venue("A", fee=9.0), venue("B", fee=9.0), min_net_edge_bps=5.25))
    w.market(b=(100.25, 100.26))
    assert w.check(xsig(bid=100.25)) == no("edge_gone")


def test_edge_recheck_with_zero_threshold_requires_strictly_positive_net():
    # fee 11.5 + slip 1 per leg: cost 25 == gross 25 -> net 0 -> not > 0
    w = World(make_cfg(venue("A", fee=11.5), venue("B", fee=11.5), min_net_edge_bps=0.0))
    w.market(b=(100.25, 100.26))
    assert w.check(xsig(bid=100.25)) == no("edge_gone")
    # slip 0.75 per leg: cost 24.5 -> net 0.5 > 0
    w = World(make_cfg(venue("A", fee=11.5, slip=0.75), venue("B", fee=11.5, slip=0.75), min_net_edge_bps=0.0))
    w.market(b=(100.25, 100.26))
    assert w.check(xsig(bid=100.25)) == ok(2.0)


# --------------------------------------------------------------------------- reason codes: positions & sizing


def test_max_open_positions_applies_to_reference_lag_entries_only():
    w = World()
    w.market()
    assert w.check(lagsig(size=1.5), open_positions=1) == no("max_open_positions")
    assert w.check(lagsig(size=1.5), open_positions=0) == ok(1.5)
    assert w.check(xsig(size=2.0), open_positions=5) == ok(2.0)  # an arb opens no position

    w2 = World(make_cfg(max_open_positions=2))
    w2.market()
    assert w2.check(lagsig(size=1.5), open_positions=1) == ok(1.5)
    assert w2.check(lagsig(size=1.5), open_positions=2) == no("max_open_positions")


def test_exposure_limit_when_existing_exposure_uses_all_headroom():
    w = World()
    w.market()
    w.pf.apply_fill("A", SYM, Side.BUY, 10.0, 100.0, 0.0)  # +10 BTC * 100.15 = 1001.5 > 1000
    assert w.check(xsig()) == no("exposure_limit")
    assert w.check(lagsig()) == no("exposure_limit")

    w = World()
    w.market()
    w.pf.apply_fill("B", SYM, Side.SELL, 10.0, 100.30, 0.0)  # -10 BTC: |-10| * 100.15 = 1001.5
    assert w.risk.net_exposure_notional(w.book) == pytest.approx(1001.5)
    assert w.check(xsig()) == no("exposure_limit")


def test_exposure_limit_when_headroom_leaves_less_than_min_notional():
    w = World()
    w.market()
    # +9.97 BTC * 100.15 = 998.4955; headroom 1.5045 / 100 = 0.015045 -> 0.015 BTC = $1.50 < $5
    w.pf.apply_fill("A", SYM, Side.BUY, 9.97, 100.0, 0.0)
    assert w.check(xsig(size=2.0)) == no("exposure_limit")


def test_insufficient_inventory_names_the_venue():
    w = World(balances={"A": {"USDT": 1e6, "BTC": 100.0}, "B": {"USDT": 1e6, "BTC": 0.0}})
    w.market()
    assert w.check(xsig()) == no("insufficient_inventory:B")  # nothing to sell on B

    w = World(balances={"A": {"USDT": 0.0, "BTC": 100.0}, "B": {"USDT": 1e6, "BTC": 100.0}})
    w.market()
    assert w.check(xsig()) == no("insufficient_inventory:A")  # no cash to buy on A

    # 0.03 BTC on B is sellable but 0.03 * 100.30 = $3.01 < $5: still the inventory that binds
    w = World(balances={"A": {"USDT": 1e6, "BTC": 100.0}, "B": {"USDT": 1e6, "BTC": 0.03}})
    w.market()
    assert w.check(xsig()) == no("insufficient_inventory:B")

    # a directional SELL needs base on its own venue (spot cannot short)
    w = World(balances={"A": {"USDT": 1e6, "BTC": 0.0}, "B": {"USDT": 1e6, "BTC": 100.0}})
    w.market()
    assert w.check(lagsig(side=Side.SELL, price=99.99)) == no("insufficient_inventory:A")


def test_below_min_notional_on_either_leg():
    w = World()
    w.market()
    assert w.check(xsig(size=0.04)) == no("below_min_notional")  # 0.04 * 100 = $4 < $5

    w = World(make_cfg(venue("A"), venue("B", min_notional=10.0)))
    w.market()
    # buy 0.099 * 100 = $9.90 >= $5 on A, but sell 0.099 * 100.30 = $9.93 < $10 on B
    assert w.check(xsig(size=0.099)) == no("below_min_notional")
    assert w.check(xsig(size=0.1)) == ok(0.1)  # 0.1 * 100.30 = $10.03


def test_reason_precedence_follows_the_documented_order():
    w = World(make_cfg(max_trades_per_minute=1))
    w.risk.on_execution(report(ExecutionOutcome.COMPLETED))  # 1 trade in the window
    w.risk.trip("manual")
    assert w.check(xsig()) == no("halted:manual")  # beats rate limit and an empty book
    w.risk.reset()
    assert w.check(xsig()) == no("rate_limit")  # beats the empty book
    w.at(T0 + 60)
    assert w.check(xsig()) == no("no_quote:A")

    w.thin("B")  # B thin, and will be stale
    w.at(T0 + 62)
    w.thick("A")
    assert w.check(xsig()) == no("stale_quote:B")  # stale beats low liquidity

    w.thin("A")
    w.quote("B", 100.25, 100.26)  # edge gone too
    assert w.check(xsig()) == no("low_liquidity:A")  # liquidity beats edge

    w2 = World(balances={"A": {"USDT": 0.0, "BTC": 0.0}, "B": {"USDT": 0.0, "BTC": 0.0}})
    w2.market(b=(100.25, 100.26))
    assert w2.check(xsig()) == no("edge_gone")  # edge beats inventory
    assert w2.check(lagsig(), open_positions=1) == no("max_open_positions")  # beats inventory

    # Tie at zero between exposure headroom and inventory: exposure is reported (listed first).
    # Both books have mid exactly 100, +10 BTC -> exposure 1000.0 == limit -> headroom 0.0;
    # the buy left A's cash at -1000 -> buying power 0.0.
    w3 = World(balances={"A": {"USDT": 0.0, "BTC": 0.0}, "B": {"USDT": 0.0, "BTC": 0.0}})
    w3.market(a=(99.5, 100.5), b=(99.5, 100.5))
    w3.pf.apply_fill("A", SYM, Side.BUY, 10.0, 100.0, 0.0)
    assert w3.risk.net_exposure_notional(w3.book) == 1000.0
    assert w3.check(lagsig(price=100.5)) == no("exposure_limit")


# --------------------------------------------------------------------------- liquidity gate


def test_liquidity_gate_blocks_immediately_and_reopens_after_continuous_recovery():
    w = World()  # floor 2000, recovery 5 s
    w.market()
    assert w.check(xsig()) == ok(2.0)

    w.at(T0 + 1).thin("A")  # depth 999.9: blocked at once
    assert not w.risk.tradable("A", SYM)
    assert w.check(xsig()) == no("low_liquidity:A")

    w.at(T0 + 2).market()  # depth back above the floor: recovery starts at T0+2
    assert not w.risk.tradable("A", SYM)
    assert w.check(xsig()) == no("low_liquidity:A")  # gate still closed although depth is fine
    w.at(T0 + 4).thick("A")
    assert not w.risk.tradable("A", SYM)

    w.at(T0 + 5).thin("A")  # dip: the timer resets
    assert not w.risk.tradable("A", SYM)
    w.at(T0 + 6).thick("A")  # recovery restarts at T0+6
    for t in (T0 + 7, T0 + 8, T0 + 9, T0 + 10):  # T0+7 is 5 s after the first recovery start
        w.at(t).thick("A")
        assert not w.risk.tradable("A", SYM), t
    w.at(T0 + 10.5)
    assert not w.risk.tradable("A", SYM)  # 4.5 s of good depth

    w.at(T0 + 11)
    assert w.risk.tradable("A", SYM)  # 5 s since T0+6, all updates >= floor
    w.market()
    assert w.check(xsig()) == ok(2.0)
    assert w.risk.tradable("B", SYM)  # B was never affected


def test_liquidity_gate_with_zero_recovery_reopens_on_first_good_quote():
    w = World(make_cfg(liquidity_recovery_s=0.0))
    w.thin("A")
    assert not w.risk.tradable("A", SYM)
    w.thick("A")
    assert w.risk.tradable("A", SYM)


def test_invalid_quote_counts_as_no_liquidity():
    w = World()
    w.market()
    w.at(T0 + 1)
    crossed = Quote(venue="A", symbol=SYM, bid=100.5, bid_size=50.0, ask=100.0, ask_size=50.0, ts_local=T0 + 1)
    assert not w.book.update(crossed)  # the book drops it ...
    w.risk.on_quote(crossed)  # ... the gate treats it as a broken book
    assert not w.risk.tradable("A", SYM)
    w.at(T0 + 1.2).market()
    assert w.check(xsig()) == no("low_liquidity:A")
    w.at(T0 + 6.2).market()
    assert w.check(xsig()) == ok(2.0)


# --------------------------------------------------------------------------- connectivity


def test_disconnected_venue_is_untradable_until_it_reconnects():
    w = World()
    w.market()
    w.at(T0 + 0.5)
    w.risk.on_feed_status(FeedStatus(venue="A", connected=False, ts_local=T0 + 0.5, reason="stall"))
    assert not w.risk.tradable("A", SYM)
    assert w.risk.tradable("B", SYM)
    assert w.check(xsig()) == no("stale_quote:A")  # the old A quote is still young but unusable

    w.book.invalidate_venue("A")  # what the Bot does on disconnect
    assert w.check(xsig()) == no("no_quote:A")

    w.at(T0 + 1).market()  # a quote alone does not make a disconnected venue usable
    assert w.check(xsig()) == no("stale_quote:A")

    w.risk.on_feed_status(FeedStatus(venue="A", connected=True, ts_local=T0 + 1))
    assert w.risk.tradable("A", SYM)
    assert w.check(xsig()) == ok(2.0)


def test_disconnect_restarts_liquidity_recovery():
    w = World()
    w.thin("A")  # blocked at T0
    w.at(T0 + 1).thick("A")  # recovering since T0+1
    w.at(T0 + 3)
    w.risk.on_feed_status(FeedStatus(venue="A", connected=False, ts_local=T0 + 3))
    w.at(T0 + 4)
    w.risk.on_feed_status(FeedStatus(venue="A", connected=True, ts_local=T0 + 4))
    w.thick("A")  # recovery restarts at T0+4
    w.at(T0 + 6).thick("A")  # 5 s after T0+1, but only 2 s since the reconnect
    assert not w.risk.tradable("A", SYM)
    w.at(T0 + 9).thick("A")
    assert w.risk.tradable("A", SYM)


# --------------------------------------------------------------------------- kill switch


@pytest.mark.parametrize(
    ("outcome", "why"),
    [(ExecutionOutcome.RESIDUAL, "residual"), (ExecutionOutcome.UNKNOWN, "unknown")],
)
def test_residual_or_unknown_trips_immediately(outcome, why):
    w = World()
    w.market()
    w.risk.on_execution(report(outcome, pnl=-1.0))
    assert w.risk.halted
    assert w.risk.halt_reason == why
    assert w.check(xsig()) == no(f"halted:{why}")


def test_daily_loss_limit_trips_at_minus_limit():
    w = World()  # limit 50
    w.risk.on_execution(report(ExecutionOutcome.COMPLETED, pnl=-30.0))
    w.risk.on_execution(report(ExecutionOutcome.COMPLETED, pnl=-19.0))
    assert w.risk.daily_pnl == -49.0
    assert not w.risk.halted
    w.risk.on_execution(report(ExecutionOutcome.COMPLETED, pnl=-1.0))  # -50 <= -50
    assert w.risk.daily_pnl == -50.0
    assert w.risk.halt_reason == "daily_loss_limit"


def test_consecutive_hedge_failures_reset_on_success_and_ignore_no_fill():
    w = World()  # limit 3
    F, C, N = ExecutionOutcome.FLATTENED, ExecutionOutcome.COMPLETED, ExecutionOutcome.NO_FILL

    def feed(outcome: ExecutionOutcome) -> int:
        w.risk.on_execution(report(outcome, filled=0.0 if outcome is N else 1.0))
        return w.risk.consecutive_hedge_failures

    assert [feed(o) for o in (F, F, C)] == [1, 2, 0]  # COMPLETED resets
    assert [feed(o) for o in (F, N, F)] == [1, 1, 2]  # NO_FILL leaves the streak alone
    assert feed(ExecutionOutcome.OPENED) == 0
    assert [feed(o) for o in (F, F)] == [1, 2]
    assert feed(ExecutionOutcome.CLOSED) == 0
    assert not w.risk.halted
    assert [feed(o) for o in (F, F)] == [1, 2]
    assert not w.risk.halted
    assert feed(F) == 3
    assert w.risk.halt_reason == "consecutive_hedge_failures"

    w.risk.reset()
    assert not w.risk.halted
    assert w.risk.consecutive_hedge_failures == 0


def test_halted_manager_rejects_everything_until_reset():
    w = World()
    w.risk.trip("operator stop")
    w.risk.trip("second cause")  # the first cause is kept
    assert w.risk.halted and w.risk.halt_reason == "operator stop"
    # rejected before any market check: even with an empty book
    assert w.check(xsig()) == no("halted:operator stop")
    w.market()
    assert w.check(xsig()) == no("halted:operator stop")
    assert w.check(lagsig()) == no("halted:operator stop")
    w.risk.on_execution(report(ExecutionOutcome.CLOSED, pnl=2.5))  # still books PnL (exits run)
    assert w.risk.daily_pnl == 2.5
    assert w.check(xsig()) == no("halted:operator stop")

    w.risk.reset()
    assert not w.risk.halted and w.risk.halt_reason is None
    assert w.check(xsig()) == ok(2.0)


# --------------------------------------------------------------------------- daily PnL bucket


def test_daily_pnl_rolls_over_at_utc_midnight():
    start = datetime(2026, 10, 27, 23, 59, tzinfo=timezone.utc).timestamp()
    w = World(start=start)
    w.risk.on_execution(report(ExecutionOutcome.FLATTENED, pnl=-40.0))
    w.at(start + 30)
    w.risk.on_execution(report(ExecutionOutcome.COMPLETED, pnl=5.0))
    assert w.risk.daily_pnl == -35.0

    w.at(datetime(2026, 10, 28, 0, 0, tzinfo=timezone.utc).timestamp())  # new UTC day, no report needed
    assert w.risk.daily_pnl == 0.0
    w.risk.on_execution(report(ExecutionOutcome.COMPLETED, pnl=-40.0))
    assert w.risk.daily_pnl == -40.0  # would be -75 without the rollover
    assert not w.risk.halted
    w.risk.on_execution(report(ExecutionOutcome.COMPLETED, pnl=-10.0))
    assert w.risk.daily_pnl == -50.0
    assert w.risk.halt_reason == "daily_loss_limit"


def test_daily_loss_halt_survives_rollover_and_holds_for_the_rest_of_the_day():
    start = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc).timestamp()
    w = World(start=start)
    w.risk.on_execution(report(ExecutionOutcome.COMPLETED, pnl=-60.0))
    assert w.risk.halt_reason == "daily_loss_limit"

    # operator resets the same day: the day is still past its limit, so the next check re-trips
    w.risk.reset()
    w.market()
    assert w.check(xsig()) == no("halted:daily_loss_limit")
    assert w.risk.halted

    # a new UTC day does not clear the kill switch by itself ...
    w.at(datetime(2026, 10, 28, 0, 0, 1, tzinfo=timezone.utc).timestamp())
    w.market()
    assert w.risk.daily_pnl == 0.0
    assert w.check(xsig()) == no("halted:daily_loss_limit")
    # ... the operator does
    w.risk.reset()
    assert w.check(xsig()) == ok(2.0)


# --------------------------------------------------------------------------- trade rate


def test_trades_per_minute_counts_only_reports_with_fills_in_a_sliding_window():
    w = World(make_cfg(max_trades_per_minute=3))
    for t in (T0, T0 + 10, T0 + 20):
        w.at(t)
        w.risk.on_execution(report(ExecutionOutcome.COMPLETED, filled=0.5))
    w.at(T0 + 25)
    w.risk.on_execution(report(ExecutionOutcome.NO_FILL, filled=0.0))
    w.risk.on_execution(report(ExecutionOutcome.NO_FILL, filled=0.0, status=OrderStatus.REJECTED))
    assert w.risk.trades_last_minute == 3

    w.at(T0 + 30).market()
    assert w.check(xsig()) == no("rate_limit")
    w.at(T0 + 59.999).market()
    assert w.check(xsig()) == no("rate_limit")  # the T0 trade is 59.999 s old
    w.at(T0 + 60).market()
    assert w.risk.trades_last_minute == 2  # the T0 trade left the window
    assert w.check(xsig()) == ok(2.0)

    w.risk.on_execution(report(ExecutionOutcome.FLATTENED, filled=0.5))  # partial fills count
    assert w.check(xsig()) == no("rate_limit")
    w.at(T0 + 70).market()  # the T0+10 trade expires
    assert w.check(xsig()) == ok(2.0)


# --------------------------------------------------------------------------- exposure marking


def test_net_exposure_notional_sums_abs_base_change_at_mid():
    w = World()
    w.market()
    assert w.risk.net_exposure_notional(w.book) == 0.0
    w.pf.apply_fill("A", SYM, Side.BUY, 7.0, 100.0, 0.0)
    w.pf.apply_fill("B", SYM, Side.SELL, 10.0, 100.30, 0.0)  # net -3 BTC
    assert w.risk.net_exposure_notional(w.book) == pytest.approx(3 * 100.15)


def test_net_exposure_falls_back_to_last_seen_mid_then_to_unbounded():
    w = World()
    w.market()  # last quote seen: B, mid 100.305
    w.pf.apply_fill("A", SYM, Side.BUY, 7.0, 100.0, 0.0)
    w.book.invalidate_venue("A")
    w.book.invalidate_venue("B")
    assert w.risk.net_exposure_notional(w.book) == pytest.approx(7 * 100.305)

    blind = RiskManager(w.cfg, w.pf, w.clock)  # never saw a quote, empty book
    assert blind.net_exposure_notional(w.book) == math.inf

    dust = Portfolio(rich())
    dust.apply_fill("A", SYM, Side.BUY, 0.0005, 100.0, 0.0)  # half a lot: dust, not exposure
    assert RiskManager(w.cfg, dust, w.clock).net_exposure_notional(QuoteBook()) == 0.0


# --------------------------------------------------------------------------- review findings (regressions)


def test_partial_exits_of_a_position_are_not_hedge_failures():
    w = World()
    for _ in range(5):  # one position closed in several IOCs: FLATTENED partial exits with a position id
        partial = report(ExecutionOutcome.FLATTENED)
        partial.position_id = "pos-1"
        w.risk.on_execution(partial)
    assert w.risk.consecutive_hedge_failures == 0 and not w.risk.halted
    for _ in range(3):  # unequal fills of cross-venue arbs still count
        w.risk.on_execution(report(ExecutionOutcome.FLATTENED))
    assert w.risk.halt_reason == "consecutive_hedge_failures"


def test_sell_leg_min_notional_is_checked_at_its_limit_price():
    # B's minimum is 10.03. 0.1 * bid 100.30 = 10.03 clears it, but the SELL leg's limit may be as low as
    # 100.30 * (1 - 5 bps) = 100.24985 and venues check the notional at the limit: 10.025 < 10.03.
    w = World(make_cfg(venue("A"), venue("B", min_notional=10.03)))
    w.market()
    assert w.check(xsig(size=0.1)) == no("below_min_notional")
    assert w.check(xsig(size=0.101)) == ok(0.101)  # 0.101 * 100.24985 = 10.125


def test_inventory_reserved_for_open_positions_is_not_tradable():
    w = World(balances={"A": {"USDT": 1e6, "BTC": 100.0}, "B": {"USDT": 1e6, "BTC": 1.0}})
    w.market()
    assert w.check(xsig(size=0.5)) == ok(0.5)
    w.pf.set_reservations(lambda: {"B": {"BTC": 1.0}})  # an open long holds B's only BTC
    assert w.check(xsig(size=0.5)) == no("insufficient_inventory:B")
    w.pf.set_reservations(lambda: {"A": {"USDT": 1e6}})  # an open short needs A's cash to buy back
    assert w.check(xsig(size=0.5)) == no("insufficient_inventory:A")
