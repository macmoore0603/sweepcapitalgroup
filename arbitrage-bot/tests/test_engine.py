"""Tests for arbbot.execution.engine: two-leg arbs, hedge/unwind, reconciliation, positions.

Expected numbers are worked out by hand. Default world: venues A and B,
BTC-USDT, tick 0.01, lot 0.001, taker fee 10 bps (fake clients charge
qty * price * 10 bps unless a test says otherwise). Book: A 99.99/100.00
(mid 99.995), B 100.30/100.31 (mid 100.305). Execution: max_slippage 5 bps,
unwind_slippage 50 bps, hedge_retry on, leg timeout 2 s (50 ms in timeout tests).
Portfolio: A holds 1000 USDT, B holds 2 BTC.

Entry limits: BUY A = floor_tick(100.00 * 1.0005) = 100.05,
SELL B = ceil_tick(100.30 * 0.9995 = 100.24985) = 100.25.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal

import pytest

from arbbot.clock import SimClock
from arbbot.config import (
    BotConfig,
    ExecutionConfig,
    InstrumentConfig,
    ReferenceLagConfig,
    VenueConfig,
)
from arbbot.execution.base import ExchangeError
from arbbot.execution.engine import ExecutionEngine
from arbbot.execution.paper import PaperExchange, simclock_sleep_until
from arbbot.feeds.base import QuoteBook
from arbbot.models import (
    ExecutionOutcome,
    Leg,
    OrderRequest,
    OrderResult,
    OrderStatus,
    Position,
    Quote,
    Side,
    Signal,
    SignalKind,
)
from arbbot.portfolio import Portfolio

SYM = "BTC-USDT"
T0 = 1000.0
ABS = 1e-9


# --------------------------------------------------------------------------- fakes


@dataclass
class Fill:
    """Scripted IOC outcome: fill ``qty`` at ``price`` (0 qty -> EXPIRED). Fee defaults to 10 bps."""

    qty: float
    price: float = 0.0
    fee: float | None = None
    status: OrderStatus | None = None
    unchecked: bool = False  # skip the limit/qty sanity checks (to script a misbehaving venue)


class Hang:
    """place_ioc never returns (the engine's leg timeout must fire)."""


Action = Fill | Hang | Exception | Callable[[OrderRequest], "Action"]


def result(req: OrderRequest, qty: float, price: float, fee: float | None = None,
           status: OrderStatus | None = None) -> OrderResult:
    if fee is None:
        fee = qty * price * 10 / 1e4
    if status is None:
        status = (OrderStatus.EXPIRED if qty <= 0
                  else OrderStatus.FILLED if qty >= req.qty else OrderStatus.PARTIALLY_FILLED)
    return OrderResult(req.client_id, req.venue, req.symbol, req.side, req.qty, qty,
                       price if qty > 0 else 0.0, fee if qty > 0 else 0.0, status, T0)


class FakeClient:
    """Scripted ExchangeClient. Records every request and query; checks fills respect the limit."""

    def __init__(self, venue: str, *script: Action,
                 query: OrderResult | Exception | Hang | Callable[[OrderRequest], OrderResult | None] | None = None
                 ) -> None:
        self.venue = venue
        self.script = list(script)
        self.requests: list[OrderRequest] = []
        self.queries: list[OrderRequest] = []
        self.query = query

    async def place_ioc(self, req: OrderRequest) -> OrderResult:
        self.requests.append(req)
        assert self.script, f"unexpected order on {self.venue}: {req}"
        action = self.script.pop(0)
        while callable(action) and not isinstance(action, (Fill, Hang, Exception)):
            action = action(req)
        if isinstance(action, Hang):
            await asyncio.Event().wait()
        if isinstance(action, Exception):
            raise action
        assert isinstance(action, Fill)
        if action.qty > 0 and not action.unchecked:
            assert action.qty <= req.qty
            if req.side is Side.BUY:
                assert action.price <= req.limit_price, "scripted fill violates the BUY limit"
            else:
                assert action.price >= req.limit_price, "scripted fill violates the SELL limit"
        return result(req, action.qty, action.price, action.fee, action.status)

    async def query_order(self, req: OrderRequest) -> OrderResult | None:
        self.queries.append(req)
        q = self.query
        if isinstance(q, Hang):
            await asyncio.Event().wait()
        if isinstance(q, Exception):
            raise q
        if callable(q) and not isinstance(q, OrderResult):
            return q(req)
        return q


class CountingPortfolio(Portfolio):
    def __init__(self, balances: dict[str, dict[str, float]]) -> None:
        super().__init__(balances)
        self.fills: list[tuple[str, str, Side, float, float, float]] = []

    def apply_fill(self, venue: str, symbol: str, side: Side, qty: float, price: float, fee: float) -> None:
        self.fills.append((venue, symbol, side, qty, price, fee))
        super().apply_fill(venue, symbol, side, qty, price, fee)


# --------------------------------------------------------------------------- world


def venue(name: str, *, lot: float = 0.001, tick: float = 0.01, latency_ms: float = 50.0) -> VenueConfig:
    return VenueConfig(
        name=name,
        feed="binance",
        taker_fee_bps=10.0,
        slippage_bps=1.0,
        latency_ms=latency_ms,
        instruments=(InstrumentConfig(symbol=SYM, venue_symbol="BTCUSDT", tick_size=tick, lot_size=lot),),
    )


def make_cfg(*venues: VenueConfig, hedge_retry: bool = True, leg_timeout_ms: float = 2000.0) -> BotConfig:
    return BotConfig(
        venues=venues or (venue("A"), venue("B")),
        execution=ExecutionConfig(
            leg_timeout_ms=leg_timeout_ms, max_slippage_bps=5.0, hedge_retry=hedge_retry, unwind_slippage_bps=50.0
        ),
        reference_lag=ReferenceLagConfig(max_hold_s=45.0),
    )


def q(venue_name: str, bid: float, ask: float, size: float = 50.0, ts: float = T0) -> Quote:
    return Quote(venue_name, SYM, bid, size, ask, size, ts_local=ts)


def default_book() -> QuoteBook:
    book = QuoteBook()
    book.update(q("A", 99.99, 100.00))
    book.update(q("B", 100.30, 100.31))
    return book


def portfolio() -> CountingPortfolio:
    return CountingPortfolio({"A": {"USDT": 1000.0}, "B": {"BTC": 2.0}})


@dataclass
class World:
    engine: ExecutionEngine
    a: FakeClient
    b: FakeClient
    pf: CountingPortfolio
    book: QuoteBook
    clock: SimClock


def world(a: FakeClient, b: FakeClient, *, cfg: BotConfig | None = None, book: QuoteBook | None = None) -> World:
    clock = SimClock(T0)
    book = book or default_book()
    pf = portfolio()
    engine = ExecutionEngine(cfg or make_cfg(), {"A": a, "B": b}, pf, book, clock)
    return World(engine, a, b, pf, book, clock)


def arb_signal(size: float = 1.0, buy_venue: str = "A", sell_venue: str = "B") -> Signal:
    return Signal(
        id="sig-1",
        kind=SignalKind.CROSS_VENUE,
        symbol=SYM,
        market=f"{SYM} buy@{buy_venue} sell@{sell_venue}",
        legs=(Leg(buy_venue, SYM, Side.BUY, 100.00, 50.0), Leg(sell_venue, SYM, Side.SELL, 100.30, 50.0)),
        size=size,
        gross_edge_bps=30.0,
        cost_bps=22.0,
        net_edge_bps=8.0,
        expected_pnl=0.08,
        entry=100.00,
        stop=99.5,
        target=100.30,
        ts=T0,
    )


def lag_signal(venue_name: str, side: Side, price: float, *, stop: float, target: float,
               max_hold_s: float | None = 30.0) -> Signal:
    return Signal(
        id="lag-1",
        kind=SignalKind.REFERENCE_LAG,
        symbol=SYM,
        market=f"{SYM} {side.value}@{venue_name}",
        legs=(Leg(venue_name, SYM, side, price, 50.0),),
        size=0.5,
        gross_edge_bps=40.0,
        cost_bps=22.0,
        net_edge_bps=18.0,
        expected_pnl=0.1,
        entry=price,
        stop=stop,
        target=target,
        ts=T0,
        max_hold_s=max_hold_s,
    )


def on_grid(price: float, tick: float) -> bool:
    return (Decimal(repr(price)) / Decimal(repr(tick))) % 1 == 0


# --------------------------------------------------------------------------- equal fills


async def test_both_legs_fill_completed_with_exact_pnl_and_portfolio() -> None:
    w = world(FakeClient("A", Fill(1.0, 100.00)), FakeClient("B", Fill(1.0, 100.30)))
    rep = await w.engine.execute(arb_signal(), 1.0)

    assert rep.outcome is ExecutionOutcome.COMPLETED
    assert rep.signal_id == "sig-1"
    assert rep.hedged_qty == 1.0
    assert rep.residual_qty == 0.0
    assert rep.fees == pytest.approx(0.1 + 0.1003, abs=ABS)
    assert rep.realized_pnl == pytest.approx(100.30 - 100.00 - 0.2003, abs=ABS)  # 0.0997
    assert [o.status for o in rep.orders] == [OrderStatus.FILLED, OrderStatus.FILLED]
    assert rep.started_ts == T0 and rep.finished_ts == T0

    (ra,), (rb,) = w.a.requests, w.b.requests
    assert (ra.venue, ra.side, ra.qty, ra.limit_price, ra.tif) == ("A", Side.BUY, 1.0, 100.05, "IOC")
    assert (rb.venue, rb.side, rb.qty, rb.limit_price) == ("B", Side.SELL, 1.0, 100.25)
    assert ra.client_id != rb.client_id and ra.client_id.startswith("arb-")

    # exactly one portfolio update per fill
    assert w.pf.fills == [
        ("A", SYM, Side.BUY, 1.0, 100.00, pytest.approx(0.1, abs=ABS)),
        ("B", SYM, Side.SELL, 1.0, 100.30, pytest.approx(0.1003, abs=ABS)),
    ]
    assert w.pf.balance("A", "BTC") == 1.0
    assert w.pf.balance("A", "USDT") == pytest.approx(1000 - 100 - 0.1, abs=ABS)
    assert w.pf.balance("B", "BTC") == 1.0
    assert w.pf.balance("B", "USDT") == pytest.approx(100.30 - 0.1003, abs=ABS)


async def test_equal_partial_fills_complete_at_the_filled_qty() -> None:
    w = world(FakeClient("A", Fill(0.4, 100.00)), FakeClient("B", Fill(0.4, 100.30)))
    rep = await w.engine.execute(arb_signal(), 1.0)
    assert rep.outcome is ExecutionOutcome.COMPLETED
    assert rep.hedged_qty == 0.4
    assert rep.realized_pnl == pytest.approx(0.4 * 0.30 - 0.04 - 0.04012, abs=ABS)
    assert len(w.pf.fills) == 2


async def test_neither_fills_no_fill() -> None:
    w = world(FakeClient("A", Fill(0.0)), FakeClient("B", Fill(0.0)))
    rep = await w.engine.execute(arb_signal(), 1.0)
    assert rep.outcome is ExecutionOutcome.NO_FILL
    assert [o.status for o in rep.orders] == [OrderStatus.EXPIRED, OrderStatus.EXPIRED]
    assert (rep.realized_pnl, rep.fees, rep.hedged_qty, rep.residual_qty) == (0.0, 0.0, 0.0, 0.0)
    assert w.pf.fills == []
    assert len(w.a.requests) == 1 and len(w.b.requests) == 1  # nothing to hedge


async def test_rejected_leg_is_noted_and_the_other_leg_is_unwound() -> None:
    w = world(FakeClient("A", Fill(0.0, status=OrderStatus.REJECTED), Fill(1.0, 100.01)),
              FakeClient("B", Fill(1.0, 100.30)))
    rep = await w.engine.execute(arb_signal(), 1.0)
    assert any("rejected" in n for n in rep.notes)
    hedge = w.a.requests[1]  # buy back the 1.0 sold on B, first on A (the hedge venue)
    assert (hedge.side, hedge.qty, hedge.limit_price) == (Side.BUY, 1.0, 100.05)
    assert rep.outcome is ExecutionOutcome.FLATTENED
    assert rep.realized_pnl == pytest.approx(100.30 - 100.01 - 0.1003 - 0.10001, abs=ABS)


async def test_size_below_common_lot_sends_nothing() -> None:
    w = world(FakeClient("A"), FakeClient("B"))
    rep = await w.engine.execute(arb_signal(), 0.0009)
    assert rep.outcome is ExecutionOutcome.NO_FILL
    assert rep.orders == [] and w.a.requests == [] and w.b.requests == []


async def test_malformed_signal_raises_before_any_order() -> None:
    w = world(FakeClient("A"), FakeClient("B"))
    sig = arb_signal()
    with pytest.raises(ValueError):
        await w.engine.execute(replace(sig, legs=(sig.legs[0], replace(sig.legs[1], venue="A"))), 1.0)
    with pytest.raises(ValueError):
        await w.engine.execute(replace(sig, kind=SignalKind.REFERENCE_LAG), 1.0)
    with pytest.raises(ValueError):  # venue C is not configured
        await w.engine.execute(replace(sig, legs=(sig.legs[0], replace(sig.legs[1], venue="C"))), 1.0)
    assert w.a.requests == [] and w.b.requests == []

    w = world(FakeClient("A"), FakeClient("B"), cfg=make_cfg(venue("A"), venue("B"), venue("C")))
    with pytest.raises(ValueError, match="no exchange client"):  # configured, but no client for C
        await w.engine.execute(replace(sig, legs=(sig.legs[0], replace(sig.legs[1], venue="C"))), 1.0)
    assert w.a.requests == []


# --------------------------------------------------------------------------- unequal: long excess


async def test_buy_over_fill_is_hedged_on_the_sell_venue() -> None:
    w = world(FakeClient("A", Fill(1.0, 100.00)), FakeClient("B", Fill(0.4, 100.30), Fill(0.6, 100.28)))
    rep = await w.engine.execute(arb_signal(), 1.0)

    assert rep.outcome is ExecutionOutcome.FLATTENED
    hedge = w.b.requests[1]
    # max(ceil(100.30 * 0.9995) = 100.25, ceil(100.00 * 0.995) = 99.50)
    assert (hedge.venue, hedge.side, hedge.qty, hedge.limit_price) == ("B", Side.SELL, 0.6, 100.25)
    assert len(w.a.requests) == 1  # no unwind needed
    assert rep.hedged_qty == 1.0 and rep.residual_qty == 0.0
    assert rep.fees == pytest.approx(0.1 + 0.04012 + 0.060168, abs=ABS)
    assert rep.realized_pnl == pytest.approx(0.4 * 100.30 + 0.6 * 100.28 - 100.00 - 0.200288, abs=ABS)  # 0.087712
    assert len(w.pf.fills) == 3
    assert w.pf.balance("B", "BTC") == pytest.approx(1.0, abs=ABS)
    assert w.pf.balance("A", "BTC") == 1.0


async def test_hedge_venue_without_liquidity_unwinds_on_the_buy_venue() -> None:
    w = world(FakeClient("A", Fill(1.0, 100.00), Fill(0.6, 99.99)),
              FakeClient("B", Fill(0.4, 100.30), Fill(0.0)))
    rep = await w.engine.execute(arb_signal(), 1.0)

    assert rep.outcome is ExecutionOutcome.FLATTENED
    hedge, unwind = w.b.requests[1], w.a.requests[1]
    assert (hedge.side, hedge.qty) == (Side.SELL, 0.6)
    assert (unwind.venue, unwind.side, unwind.qty, unwind.limit_price) == ("A", Side.SELL, 0.6, 99.5)
    assert [o.status for o in rep.orders] == [
        OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED, OrderStatus.EXPIRED, OrderStatus.FILLED
    ]
    assert rep.residual_qty == 0.0 and rep.hedged_qty == 1.0
    assert rep.realized_pnl == pytest.approx(
        0.4 * 100.30 + 0.6 * 99.99 - 100.00 - (0.1 + 0.04012 + 0.059994), abs=ABS
    )  # -0.086114
    assert len(w.pf.fills) == 3
    assert w.pf.balance("A", "BTC") == pytest.approx(0.4, abs=ABS)
    assert w.pf.balance("A", "USDT") == pytest.approx(1000 - 100 - 0.1 + 59.994 - 0.059994, abs=ABS)
    assert w.pf.balance("B", "BTC") == pytest.approx(1.6, abs=ABS)
    assert w.pf.net_base_change("BTC") == pytest.approx(0.0, abs=ABS)


async def test_neither_hedge_nor_unwind_fills_residual_marked_at_mid() -> None:
    w = world(FakeClient("A", Fill(1.0, 100.00), Fill(0.0)), FakeClient("B", Fill(0.4, 100.30), Fill(0.0)))
    rep = await w.engine.execute(arb_signal(), 1.0)

    assert rep.outcome is ExecutionOutcome.RESIDUAL
    assert rep.residual_qty == pytest.approx(0.6, abs=ABS)
    assert rep.hedged_qty == 0.4
    # sells - buys - fees + 0.6 * mid(A) = 40.12 - 100 - 0.14012 + 0.6 * 99.995 = -0.02312
    assert rep.realized_pnl == pytest.approx(0.4 * 100.30 - 100.00 - 0.14012 + 0.6 * 99.995, abs=ABS)
    assert any("residual +0.6" in n for n in rep.notes)
    assert w.pf.net_base_change("BTC") == pytest.approx(0.6, abs=ABS)


async def test_without_hedge_retry_goes_straight_to_unwind() -> None:
    w = world(FakeClient("A", Fill(1.0, 100.00), Fill(0.6, 99.99)), FakeClient("B", Fill(0.4, 100.30)),
              cfg=make_cfg(hedge_retry=False))
    rep = await w.engine.execute(arb_signal(), 1.0)
    assert rep.outcome is ExecutionOutcome.FLATTENED
    assert len(w.b.requests) == 1
    assert w.a.requests[1].limit_price == 99.5


async def test_partial_hedge_then_unwind_rest() -> None:
    w = world(FakeClient("A", Fill(1.0, 100.00), Fill(0.3, 99.99)),
              FakeClient("B", Fill(0.4, 100.30), Fill(0.3, 100.28)))
    rep = await w.engine.execute(arb_signal(), 1.0)
    assert rep.outcome is ExecutionOutcome.FLATTENED
    assert w.b.requests[1].qty == 0.6
    assert w.a.requests[1].qty == 0.3  # exactly the rest, 0.6 - 0.3 on the lot grid
    assert rep.residual_qty == 0.0


async def test_lot_grid_arithmetic_does_not_leave_dust() -> None:
    # 0.7 - 0.4 is 0.29999999999999993 in floats; flooring that would leave 0.001 unhedged.
    w = world(FakeClient("A", Fill(0.7, 100.00)), FakeClient("B", Fill(0.4, 100.30), Fill(0.3, 100.28)))
    rep = await w.engine.execute(arb_signal(), 0.7)
    assert w.b.requests[1].qty == 0.3
    assert rep.outcome is ExecutionOutcome.FLATTENED
    assert rep.residual_qty == 0.0


# --------------------------------------------------------------------------- unequal: short excess (mirror)


async def test_sell_over_fill_is_hedged_by_buying_on_the_buy_venue() -> None:
    w = world(FakeClient("A", Fill(0.4, 100.00), Fill(0.6, 100.01)), FakeClient("B", Fill(1.0, 100.30)))
    rep = await w.engine.execute(arb_signal(), 1.0)

    assert rep.outcome is ExecutionOutcome.FLATTENED
    hedge = w.a.requests[1]
    # min(floor(100.00 * 1.0005) = 100.05, floor(100.30 * 1.005) = 100.80)
    assert (hedge.venue, hedge.side, hedge.qty, hedge.limit_price) == ("A", Side.BUY, 0.6, 100.05)
    assert len(w.b.requests) == 1
    assert rep.realized_pnl == pytest.approx(100.30 - 0.4 * 100.00 - 0.6 * 100.01 - 0.200306, abs=ABS)  # 0.093694
    assert rep.residual_qty == 0.0 and rep.hedged_qty == 1.0
    assert len(w.pf.fills) == 3


async def test_sell_over_fill_unwinds_by_buying_back_on_the_sell_venue() -> None:
    w = world(FakeClient("A", Fill(0.4, 100.00), Fill(0.0)), FakeClient("B", Fill(1.0, 100.30), Fill(0.6, 100.31)))
    rep = await w.engine.execute(arb_signal(), 1.0)

    assert rep.outcome is ExecutionOutcome.FLATTENED
    unwind = w.b.requests[1]
    assert (unwind.venue, unwind.side, unwind.qty, unwind.limit_price) == ("B", Side.BUY, 0.6, 100.80)
    assert rep.realized_pnl == pytest.approx(
        100.30 - 0.4 * 100.00 - 0.6 * 100.31 - (0.04 + 0.1003 + 0.060186), abs=ABS
    )  # -0.086486
    assert w.pf.balance("B", "BTC") == pytest.approx(2.0 - 1.0 + 0.6, abs=ABS)


async def test_sell_over_fill_residual_is_short_and_marked_at_sell_venue_mid() -> None:
    w = world(FakeClient("A", Fill(0.4, 100.00), Fill(0.0)), FakeClient("B", Fill(1.0, 100.30), Fill(0.0)))
    rep = await w.engine.execute(arb_signal(), 1.0)
    assert rep.outcome is ExecutionOutcome.RESIDUAL
    assert rep.residual_qty == pytest.approx(-0.6, abs=ABS)
    # 100.30 - 40.00 - 0.1403 - 0.6 * 100.305 = -0.0233
    assert rep.realized_pnl == pytest.approx(100.30 - 40.00 - 0.1403 - 0.6 * 100.305, abs=ABS)


# --------------------------------------------------------------------------- limit bounds


async def test_hedge_and_unwind_limits_are_clamped_to_the_unwind_band_long() -> None:
    def crash_b_then_fill(req: OrderRequest) -> Fill:
        w.book.update(q("B", 90.00, 90.01))  # the hedge venue's bid collapsed after our leg
        return Fill(0.4, 100.30)

    w = world(FakeClient("A", Fill(1.0, 100.00), Fill(0.0)), FakeClient("B", crash_b_then_fill, Fill(0.0)))
    rep = await w.engine.execute(arb_signal(), 1.0)
    hedge, unwind = w.b.requests[1], w.a.requests[1]
    floor_price = 100.00 * (1 - 50 / 1e4)  # 99.5: never sell below this
    assert hedge.limit_price == 99.5  # not ceil(90.00 * 0.9995) = 89.96
    assert unwind.limit_price == 99.5
    for r in (hedge, unwind):
        assert r.side is Side.SELL and r.limit_price >= floor_price and on_grid(r.limit_price, 0.01)
    assert rep.outcome is ExecutionOutcome.RESIDUAL


async def test_hedge_and_unwind_limits_are_clamped_to_the_unwind_band_short() -> None:
    def spike_a_then_fill(req: OrderRequest) -> Fill:
        w.book.update(q("A", 110.00, 110.01))
        return Fill(0.4, 100.00)

    w = world(FakeClient("A", spike_a_then_fill, Fill(0.0)), FakeClient("B", Fill(1.0, 100.30), Fill(0.0)))
    await w.engine.execute(arb_signal(), 1.0)
    hedge, unwind = w.a.requests[1], w.b.requests[1]
    cap = 100.30 * (1 + 50 / 1e4)  # 100.8015: never buy back above this
    assert hedge.limit_price == 100.80  # not floor(110.01 * 1.0005) = 110.06
    assert unwind.limit_price == 100.80
    for r in (hedge, unwind):
        assert r.side is Side.BUY and r.limit_price <= cap and on_grid(r.limit_price, 0.01)


async def test_unwind_band_uses_the_legs_average_fill_price_quantized_inward() -> None:
    w = world(FakeClient("A", Fill(1.0, 100.003), Fill(0.0)), FakeClient("B", Fill(0.0)),
              cfg=make_cfg(hedge_retry=False))
    await w.engine.execute(arb_signal(), 1.0)
    unwind = w.a.requests[1]
    # 100.003 * 0.995 = 99.502985 -> SELL limits round up to the tick: 99.51
    assert unwind.limit_price == 99.51
    assert unwind.limit_price >= 100.003 * 0.995


async def test_entry_limits_capped_at_max_slippage_and_tick_quantized_per_venue() -> None:
    cfg = make_cfg(venue("A", tick=0.01, lot=0.001), venue("B", tick=0.1, lot=0.01))
    w = world(FakeClient("A", Fill(0.0)), FakeClient("B", Fill(0.0)), cfg=cfg)
    await w.engine.execute(arb_signal(), 1.23456)
    (ra,), (rb,) = w.a.requests, w.b.requests
    assert ra.limit_price == 100.05 and ra.limit_price <= 100.00 * 1.0005
    assert rb.limit_price == 100.3 and rb.limit_price >= 100.30 * 0.9995  # ceil(100.24985, 0.1)
    assert on_grid(ra.limit_price, 0.01) and on_grid(rb.limit_price, 0.1)
    assert ra.qty == rb.qty == 1.23  # floored to both lots (0.001 and 0.01)


async def test_qty_is_floored_to_a_lot_both_venues_accept() -> None:
    cfg = make_cfg(venue("A", lot=0.002), venue("B", lot=0.003))
    w = world(FakeClient("A", Fill(0.0)), FakeClient("B", Fill(0.0)), cfg=cfg)
    await w.engine.execute(arb_signal(), 0.02)
    assert w.a.requests[0].qty == w.b.requests[0].qty == 0.018  # largest multiple of 0.006


async def test_entry_limits_follow_the_current_book_quote() -> None:
    book = default_book()
    book.update(q("A", 100.01, 100.02))  # moved since the signal (leg price 100.00)
    w = world(FakeClient("A", Fill(0.0)), FakeClient("B", Fill(0.0)), book=book)
    await w.engine.execute(arb_signal(), 1.0)
    assert w.a.requests[0].limit_price == 100.07  # floor(100.02 * 1.0005 = 100.07001)


async def test_entry_limits_fall_back_to_signal_prices_without_a_book_quote() -> None:
    w = world(FakeClient("A", Fill(0.0)), FakeClient("B", Fill(0.0)), book=QuoteBook())
    await w.engine.execute(arb_signal(), 1.0)
    assert w.a.requests[0].limit_price == 100.05
    assert w.b.requests[0].limit_price == 100.25


# --------------------------------------------------------------------------- timeouts and reconciliation


async def test_leg_timeout_reconciles_a_fill_then_hedges() -> None:
    a = FakeClient("A", Hang(), query=lambda req: result(req, 1.0, 100.00))
    b = FakeClient("B", Fill(0.4, 100.30), Fill(0.6, 100.29))
    w = world(a, b, cfg=make_cfg(leg_timeout_ms=50.0))
    rep = await w.engine.execute(arb_signal(), 1.0)

    assert a.queries == a.requests  # reconciled the exact order that timed out
    assert rep.outcome is ExecutionOutcome.FLATTENED
    assert rep.orders[0].status is OrderStatus.FILLED and rep.orders[0].filled_qty == 1.0
    assert (b.requests[1].side, b.requests[1].qty) == (Side.SELL, 0.6)
    assert w.pf.fills == [
        ("B", SYM, Side.SELL, 0.4, 100.30, pytest.approx(0.04012, abs=ABS)),
        ("A", SYM, Side.BUY, 1.0, 100.00, pytest.approx(0.1, abs=ABS)),
        ("B", SYM, Side.SELL, 0.6, 100.29, pytest.approx(0.060174, abs=ABS)),
    ]
    assert rep.realized_pnl == pytest.approx(0.4 * 100.30 + 0.6 * 100.29 - 100.00 - 0.200294, abs=ABS)


async def test_leg_timeout_without_a_record_is_unknown_and_nothing_is_guessed() -> None:
    a = FakeClient("A", Hang(), query=None)
    b = FakeClient("B", Fill(1.0, 100.30))
    w = world(a, b, cfg=make_cfg(leg_timeout_ms=50.0))
    rep = await w.engine.execute(arb_signal(), 1.0)

    assert rep.outcome is ExecutionOutcome.UNKNOWN
    unknown = rep.orders[0]
    assert unknown.status is OrderStatus.UNKNOWN and unknown.filled_qty == 0.0
    assert "timeout" in (unknown.error or "") and "no record" in (unknown.error or "")
    assert len(a.requests) == 1 and len(b.requests) == 1  # no hedge, no unwind
    assert w.pf.fills == [("B", SYM, Side.SELL, 1.0, 100.30, pytest.approx(0.1003, abs=ABS))]
    assert rep.residual_qty == pytest.approx(-1.0)  # known fills only
    assert any("unknown" in n for n in rep.notes)


async def test_exchange_error_is_reconciled_like_a_timeout() -> None:
    a = FakeClient("A", ExchangeError("connection reset"), query=lambda req: result(req, 1.0, 100.00))
    w = world(a, FakeClient("B", Fill(1.0, 100.30)))
    rep = await w.engine.execute(arb_signal(), 1.0)
    assert rep.outcome is ExecutionOutcome.COMPLETED
    assert a.queries == a.requests
    assert len(w.pf.fills) == 2
    assert rep.realized_pnl == pytest.approx(0.0997, abs=ABS)


async def test_exchange_error_without_record_is_unknown() -> None:
    a = FakeClient("A", ExchangeError("502"), query=None)
    w = world(a, FakeClient("B", Fill(1.0, 100.30)))
    rep = await w.engine.execute(arb_signal(), 1.0)
    assert rep.outcome is ExecutionOutcome.UNKNOWN
    assert "exchange error: 502" in (rep.orders[0].error or "")


@pytest.mark.parametrize("query", [ExchangeError("query down"), Hang()])
async def test_failed_or_hanging_query_is_unknown(query: Exception | Hang) -> None:
    a = FakeClient("A", Hang(), query=query)
    w = world(a, FakeClient("B", Fill(0.0)), cfg=make_cfg(leg_timeout_ms=50.0))
    rep = await w.engine.execute(arb_signal(), 1.0)
    assert rep.outcome is ExecutionOutcome.UNKNOWN
    assert "query failed" in (rep.orders[0].error or "")


async def test_unexpected_client_exception_is_reconciled() -> None:
    a = FakeClient("A", RuntimeError("bug"), query=lambda req: result(req, 1.0, 100.00))
    w = world(a, FakeClient("B", Fill(1.0, 100.30)))
    rep = await w.engine.execute(arb_signal(), 1.0)
    assert rep.outcome is ExecutionOutcome.COMPLETED


async def test_unknown_hedge_order_stops_further_orders() -> None:
    a = FakeClient("A", Fill(1.0, 100.00))
    b = FakeClient("B", Fill(0.4, 100.30), Hang(), query=None)
    w = world(a, b, cfg=make_cfg(leg_timeout_ms=50.0))
    rep = await w.engine.execute(arb_signal(), 1.0)
    assert rep.outcome is ExecutionOutcome.UNKNOWN
    assert len(a.requests) == 1  # no unwind on top of a hedge that may have filled
    assert rep.orders[-1].status is OrderStatus.UNKNOWN


async def test_client_reporting_unknown_is_reconciled() -> None:
    a = FakeClient("A", Fill(0.0, status=OrderStatus.UNKNOWN), query=lambda req: result(req, 1.0, 100.00))
    w = world(a, FakeClient("B", Fill(1.0, 100.30)))
    rep = await w.engine.execute(arb_signal(), 1.0)
    assert a.queries == a.requests
    assert rep.outcome is ExecutionOutcome.COMPLETED


async def test_over_filled_hedge_is_never_reported_flat() -> None:
    # A misbehaving venue fills 0.7 of a 0.6 hedge: the arb is now 0.1 short, which is not flat.
    a = FakeClient("A", Fill(1.0, 100.00))
    b = FakeClient("B", Fill(0.4, 100.30), Fill(0.7, 100.28, unchecked=True))
    w = world(a, b)
    rep = await w.engine.execute(arb_signal(), 1.0)
    assert rep.outcome is ExecutionOutcome.RESIDUAL
    assert rep.residual_qty == pytest.approx(-0.1, abs=ABS)


async def test_fill_reported_without_price_cannot_widen_the_unwind_band() -> None:
    a = FakeClient("A", Fill(1.0, 0.0, fee=0.0, unchecked=True), Fill(0.0))
    w = world(a, FakeClient("B", Fill(0.0)), cfg=make_cfg(hedge_retry=False))
    await w.engine.execute(arb_signal(), 1.0)
    assert w.a.requests[1].limit_price == 99.5  # band from the leg's quoted 100.00, not from 0


async def test_send_applies_a_fill_exactly_once() -> None:
    a = FakeClient("A", Fill(0.25, 100.00))
    w = world(a, FakeClient("B"))
    res = await w.engine.send(OrderRequest("x-1", "A", SYM, Side.BUY, 0.5, 100.05))
    assert res.status is OrderStatus.PARTIALLY_FILLED
    assert w.pf.fills == [("A", SYM, Side.BUY, 0.25, 100.00, pytest.approx(0.025, abs=ABS))]


# --------------------------------------------------------------------------- backtest timing through the engine


class TimedBook:
    def __init__(self, *timeline: tuple[float, Quote]) -> None:
        self.timeline = sorted(timeline, key=lambda x: x[0])
        self.calls: list[float] = []

    def __call__(self, symbol: str, t: float) -> Quote | None:
        self.calls.append(t)
        current = None
        for start, quote in self.timeline:
            if start <= t:
                current = quote
        return current


def paper_world(a_book: TimedBook, b_book: TimedBook) -> tuple[ExecutionEngine, SimClock, CountingPortfolio]:
    cfg = make_cfg(venue("A", latency_ms=50.0), venue("B", latency_ms=200.0))
    clock = SimClock(T0)
    sleep = simclock_sleep_until(clock)
    clients = {
        "A": PaperExchange(cfg.venue("A"), a_book, clock, sleep_until=sleep),
        "B": PaperExchange(cfg.venue("B"), b_book, clock, sleep_until=sleep),
    }
    pf = portfolio()
    return ExecutionEngine(cfg, clients, pf, default_book(), clock), clock, pf


async def test_backtest_legs_each_see_the_book_at_their_own_arrival() -> None:
    a_book = TimedBook((0.0, q("A", 99.99, 100.00, size=5.0)))
    # B: bid 100.28 from T0+0.1, collapses to 100.20 (below the 100.25 limit) at T0+0.21.
    b_book = TimedBook((0.0, q("B", 100.30, 100.31, size=5.0)), (T0 + 0.1, q("B", 100.28, 100.29, size=5.0)),
                       (T0 + 0.21, q("B", 100.20, 100.21, size=5.0)))
    engine, clock, _ = paper_world(a_book, b_book)
    rep = await engine.execute(arb_signal(), 1.0)

    assert a_book.calls == [pytest.approx(T0 + 0.05)]
    assert b_book.calls == [pytest.approx(T0 + 0.2)]  # sent at T0 like leg A, not after A advanced the clock
    assert rep.outcome is ExecutionOutcome.COMPLETED
    buy_res, sell_res = rep.orders
    assert buy_res.avg_price == pytest.approx(100.00 * 1.0001, abs=ABS)
    assert sell_res.avg_price == pytest.approx(100.28 * 0.9999, abs=ABS)
    assert clock.now() == pytest.approx(T0 + 0.2)
    assert rep.finished_ts == pytest.approx(T0 + 0.2)
    fees = 100.01 * 0.001 + 100.269972 * 0.001
    assert rep.realized_pnl == pytest.approx(100.269972 - 100.01 - fees, abs=ABS)


async def test_backtest_hedge_is_sent_after_the_legs_and_sees_its_own_arrival_book() -> None:
    a_book = TimedBook((0.0, q("A", 99.99, 100.00, size=5.0)))
    b_book = TimedBook(
        (0.0, q("B", 100.30, 100.31, size=5.0)),
        (T0 + 0.1, Quote("B", SYM, 100.28, 0.4, 100.29, 5.0, ts_local=T0 + 0.1)),  # only 0.4 bid at leg arrival
        (T0 + 0.3, q("B", 100.27, 100.28, size=5.0)),  # refilled by the time the hedge arrives
    )
    engine, clock, pf = paper_world(a_book, b_book)
    rep = await engine.execute(arb_signal(), 1.0)

    assert b_book.calls == [pytest.approx(T0 + 0.2), pytest.approx(T0 + 0.4)]  # hedge sent at T0+0.2
    assert rep.outcome is ExecutionOutcome.FLATTENED
    assert [o.filled_qty for o in rep.orders] == [1.0, 0.4, 0.6]
    hedge = rep.orders[2]
    assert hedge.avg_price == pytest.approx(100.27 * 0.9999, abs=ABS)  # 100.259973 >= limit 100.25
    fees = 0.10001 + 0.4 * 100.269972 * 0.001 + 0.6 * 100.259973 * 0.001
    assert rep.fees == pytest.approx(fees, abs=ABS)
    assert rep.realized_pnl == pytest.approx(0.4 * 100.269972 + 0.6 * 100.259973 - 100.01 - fees, abs=ABS)
    assert clock.now() == pytest.approx(T0 + 0.4)
    assert pf.net_base_change("BTC") == pytest.approx(0.0, abs=ABS)


# --------------------------------------------------------------------------- directional: enter / exit


async def test_enter_opens_a_position_from_the_signal() -> None:
    w = world(FakeClient("A", Fill(0.5, 100.00)), FakeClient("B"))
    sig = lag_signal("A", Side.BUY, 100.00, stop=99.85, target=100.50, max_hold_s=30.0)
    rep, pos = await w.engine.enter(sig, 0.5)

    assert rep.outcome is ExecutionOutcome.OPENED
    assert pos is not None and rep.position_id == pos.id
    assert (pos.venue, pos.symbol, pos.side, pos.qty, pos.entry_price) == ("A", SYM, Side.BUY, 0.5, 100.00)
    assert (pos.stop_price, pos.target_price, pos.max_hold_s) == (99.85, 100.50, 30.0)
    assert pos.signal_id == "lag-1" and pos.opened_ts == T0 and pos.exit_attempts == 0
    assert pos.entry_fee == pytest.approx(0.05, abs=ABS)
    assert rep.realized_pnl == 0.0 and rep.fees == pytest.approx(0.05, abs=ABS)
    (req,) = w.a.requests
    assert (req.side, req.qty, req.limit_price) == (Side.BUY, 0.5, 100.05)
    assert w.pf.fills == [("A", SYM, Side.BUY, 0.5, 100.00, pytest.approx(0.05, abs=ABS))]


async def test_enter_partial_fill_opens_the_filled_qty_and_defaults_max_hold() -> None:
    w = world(FakeClient("A", Fill(0.3, 100.00)), FakeClient("B"))
    sig = lag_signal("A", Side.BUY, 100.00, stop=99.85, target=100.50, max_hold_s=None)
    rep, pos = await w.engine.enter(sig, 0.5)
    assert rep.outcome is ExecutionOutcome.OPENED
    assert pos is not None and pos.qty == 0.3
    assert pos.max_hold_s == 45.0  # reference_lag.max_hold_s


async def test_enter_no_fill_and_unknown_open_nothing() -> None:
    w = world(FakeClient("A", Fill(0.0)), FakeClient("B"))
    rep, pos = await w.engine.enter(lag_signal("A", Side.BUY, 100.00, stop=99.85, target=100.5), 0.5)
    assert rep.outcome is ExecutionOutcome.NO_FILL and pos is None

    w = world(FakeClient("A", Hang(), query=None), FakeClient("B"), cfg=make_cfg(leg_timeout_ms=50.0))
    rep, pos = await w.engine.enter(lag_signal("A", Side.BUY, 100.00, stop=99.85, target=100.5), 0.5)
    assert rep.outcome is ExecutionOutcome.UNKNOWN and pos is None


async def test_exit_long_partial_then_full_close_realizes_pnl_net_of_fees() -> None:
    w = world(FakeClient("A", Fill(0.5, 100.00), Fill(0.2, 100.50), Fill(0.3, 100.40)), FakeClient("B"))
    _, pos = await w.engine.enter(lag_signal("A", Side.BUY, 100.00, stop=99.85, target=100.50), 0.5)
    assert pos is not None

    rep1 = await w.engine.exit_position(pos, "target", q("A", 100.50, 100.51))
    req1 = w.a.requests[1]
    assert (req1.side, req1.qty, req1.limit_price) == (Side.SELL, 0.5, 100.0)  # ceil(100.50 * 0.995 = 99.9975)
    assert rep1.outcome is ExecutionOutcome.FLATTENED
    assert any("partial exit (target)" in n for n in rep1.notes)
    # 0.2 * (100.50 - 100.00) - 0.05 * 0.2/0.5 - 0.0201 = 0.0599
    assert rep1.realized_pnl == pytest.approx(0.2 * 0.50 - 0.02 - 0.0201, abs=ABS)
    assert pos.qty == pytest.approx(0.3, abs=ABS) and pos.exit_attempts == 1
    assert pos.entry_fee == pytest.approx(0.03, abs=ABS)
    assert rep1.residual_qty == pytest.approx(0.3, abs=ABS)
    assert rep1.position_id == pos.id and rep1.signal_id == "lag-1"

    rep2 = await w.engine.exit_position(pos, "time", q("A", 100.40, 100.41))
    assert w.a.requests[2].qty == 0.3
    assert w.a.requests[2].limit_price == 99.9  # ceil(100.40 * 0.995 = 99.898)
    assert rep2.outcome is ExecutionOutcome.CLOSED
    # 0.3 * (100.40 - 100.00) - 0.03 - 0.03012 = 0.05988
    assert rep2.realized_pnl == pytest.approx(0.3 * 0.40 - 0.03 - 0.03012, abs=ABS)
    assert pos.qty == 0.0 and pos.exit_attempts == 2
    assert rep1.realized_pnl + rep2.realized_pnl == pytest.approx(
        0.2 * 100.50 + 0.3 * 100.40 - 0.5 * 100.00 - (0.05 + 0.0201 + 0.03012), abs=ABS
    )
    assert w.pf.balance("A", "BTC") == pytest.approx(0.0, abs=ABS)
    assert w.pf.balance("A", "USDT") == pytest.approx(1000 + 0.11978, abs=ABS)
    assert len(w.pf.fills) == 3


async def test_exit_short_partial_then_full_close_realizes_pnl_net_of_fees() -> None:
    w = world(FakeClient("A"), FakeClient("B", Fill(0.5, 100.30), Fill(0.2, 100.01), Fill(0.3, 100.05)))
    _, pos = await w.engine.enter(lag_signal("B", Side.SELL, 100.30, stop=100.45, target=100.00), 0.5)
    assert pos is not None and pos.side is Side.SELL
    assert w.b.requests[0].limit_price == 100.25
    assert pos.entry_fee == pytest.approx(0.05015, abs=ABS)

    rep1 = await w.engine.exit_position(pos, "target", q("B", 100.00, 100.01))
    req1 = w.b.requests[1]
    assert (req1.side, req1.qty, req1.limit_price) == (Side.BUY, 0.5, 100.51)  # floor(100.01 * 1.005)
    assert rep1.outcome is ExecutionOutcome.FLATTENED
    # 0.2 * (100.30 - 100.01) - 0.05015 * 0.4 - 0.020002 = 0.017938
    assert rep1.realized_pnl == pytest.approx(0.2 * 0.29 - 0.02006 - 0.020002, abs=ABS)
    assert pos.qty == pytest.approx(0.3, abs=ABS)
    assert rep1.residual_qty == pytest.approx(-0.3, abs=ABS)

    rep2 = await w.engine.exit_position(pos, "stop", q("B", 100.04, 100.05))
    assert rep2.outcome is ExecutionOutcome.CLOSED
    # 0.3 * (100.30 - 100.05) - 0.03009 - 0.030015 = 0.014895
    assert rep2.realized_pnl == pytest.approx(0.3 * 0.25 - 0.03009 - 0.030015, abs=ABS)
    assert rep1.realized_pnl + rep2.realized_pnl == pytest.approx(
        0.5 * 100.30 - 0.2 * 100.01 - 0.3 * 100.05 - (0.05015 + 0.020002 + 0.030015), abs=ABS
    )
    assert pos.qty == 0.0
    assert w.pf.balance("B", "BTC") == pytest.approx(2.0, abs=ABS)


async def test_exit_not_filled_counts_the_attempt_and_keeps_the_position() -> None:
    w = world(FakeClient("A", Fill(0.0)), FakeClient("B"))
    pos = Position("pos-x", "lag-1", "A", SYM, Side.BUY, 0.5, 100.00, 99.85, 100.50, T0, 30.0, entry_fee=0.05)
    rep = await w.engine.exit_position(pos, "stop", q("A", 99.80, 99.81))
    assert rep.outcome is ExecutionOutcome.NO_FILL
    assert w.a.requests[0].limit_price == 99.31  # ceil(99.80 * 0.995 = 99.301)
    assert (pos.qty, pos.exit_attempts, pos.entry_fee) == (0.5, 1, 0.05)
    assert rep.realized_pnl == 0.0 and rep.residual_qty == 0.5
    assert w.pf.fills == []


async def test_exit_unknown_leaves_the_position_untouched() -> None:
    w = world(FakeClient("A", Hang(), query=None), FakeClient("B"), cfg=make_cfg(leg_timeout_ms=50.0))
    pos = Position("pos-x", "lag-1", "A", SYM, Side.BUY, 0.5, 100.00, 99.85, 100.50, T0, 30.0, entry_fee=0.05)
    rep = await w.engine.exit_position(pos, "time", q("A", 100.00, 100.01))
    assert rep.outcome is ExecutionOutcome.UNKNOWN
    assert pos.qty == 0.5 and pos.exit_attempts == 1


async def test_exit_without_a_usable_quote_uses_the_book() -> None:
    w = world(FakeClient("A", Fill(0.0), Fill(0.0)), FakeClient("B"))
    pos = Position("pos-x", "lag-1", "A", SYM, Side.BUY, 0.5, 100.00, 99.85, 100.50, T0, 30.0)
    await w.engine.exit_position(pos, "time", None)
    await w.engine.exit_position(pos, "time", q("B", 50.00, 50.01))  # another venue's quote is ignored
    # book A bid 99.99 -> ceil(99.99 * 0.995 = 99.49005) = 99.5
    assert [r.limit_price for r in w.a.requests] == [99.5, 99.5]
    assert pos.exit_attempts == 2


async def test_client_ids_are_unique_and_carry_the_prefix() -> None:
    a = FakeClient("A", Fill(1.0, 100.00), Fill(0.0))
    b = FakeClient("B", Fill(0.4, 100.30), Fill(0.0))
    clock = SimClock(T0)
    engine = ExecutionEngine(make_cfg(), {"A": a, "B": b}, portfolio(), default_book(), clock,
                             client_id_prefix="bt")
    await engine.execute(arb_signal(), 1.0)
    ids = [r.client_id for r in a.requests + b.requests]
    assert len(set(ids)) == 4
    assert all(i.startswith("bt-") for i in ids)
    assert ids[0] == "bt-lfls-1"  # session stamp = base36(int(T0 * 1000)) = base36(1_000_000)


# --------------------------------------------------------------------------- review findings (regressions)


def mn_venue(name: str, *, lot: float = 0.001, min_notional: float = 5.0) -> VenueConfig:
    v = venue(name, lot=lot)
    return replace(v, instruments=(replace(v.instruments[0], min_notional=min_notional),))


async def test_excess_below_min_notional_on_every_venue_is_dust_not_residual() -> None:
    # Sold 0.999 of 1.0: the 0.001 BTC (~$0.10) excess is below both venues' $5 minimum. No hedge or
    # unwind is sent (FakeClient would fail on an unscripted order); the arb is FLATTENED with dust.
    w = world(FakeClient("A", Fill(1.0, 100.00)), FakeClient("B", Fill(0.999, 100.30)))
    rep = await w.engine.execute(arb_signal(), 1.0)
    assert rep.outcome is ExecutionOutcome.FLATTENED
    assert len(w.a.requests) == 1 and len(w.b.requests) == 1
    assert rep.residual_qty == pytest.approx(0.001, abs=ABS)
    assert "hedge: 0.001 is below the B min notional 5" in rep.notes
    assert "unwind: 0.001 is below the A min notional 5" in rep.notes
    assert any(n.startswith("dust +0.001 left") for n in rep.notes)
    # sells - buys - fees + the dust marked at A's mid 99.995
    assert rep.realized_pnl == pytest.approx(0.999 * 100.30 - 100.00 - (0.1 + 0.0999 * 1.003) + 0.001 * 99.995,
                                             abs=ABS)


async def test_excess_one_venue_can_still_trade_is_sent_there() -> None:
    cfg = make_cfg(mn_venue("A"), mn_venue("B", min_notional=0.05))
    w = world(FakeClient("A", Fill(1.0, 100.00)), FakeClient("B", Fill(0.999, 100.30), Fill(0.001, 100.28)),
              cfg=cfg)
    rep = await w.engine.execute(arb_signal(), 1.0)
    assert (w.b.requests[1].side, w.b.requests[1].qty) == (Side.SELL, 0.001)  # 0.1 USDT >= 0.05 on B
    assert rep.outcome is ExecutionOutcome.FLATTENED and rep.residual_qty == 0.0


async def test_mismatched_lots_leave_sub_lot_dust_that_is_not_residual() -> None:
    # A lot 1e-5, B lot 1e-6. B sells 0.400003, its hedge misses, A can only unwind 0.59999 of 0.599997:
    # 7e-6 is below A's lot and below B's $5 minimum, so no order can ever flatten it.
    cfg = make_cfg(mn_venue("A", lot=0.00001), mn_venue("B", lot=0.000001))
    w = world(FakeClient("A", Fill(1.0, 100.00), Fill(0.59999, 99.99)),
              FakeClient("B", Fill(0.400003, 100.30), Fill(0.0)), cfg=cfg)
    rep = await w.engine.execute(arb_signal(), 1.0)
    assert w.a.requests[1].qty == 0.59999
    assert rep.outcome is ExecutionOutcome.FLATTENED
    assert rep.residual_qty == pytest.approx(7e-06, abs=1e-12)
    assert any(n.startswith("dust +7e-06 left") for n in rep.notes)


async def test_unsendable_excess_that_is_not_dust_is_still_residual() -> None:
    # Hedge and unwind (0.6 BTC each, well above $5) both miss: that is a real RESIDUAL.
    w = world(FakeClient("A", Fill(1.0, 100.00), Fill(0.0)), FakeClient("B", Fill(0.4, 100.30), Fill(0.0)))
    rep = await w.engine.execute(arb_signal(), 1.0)
    assert rep.outcome is ExecutionOutcome.RESIDUAL and not any("dust" in n for n in rep.notes)


async def test_long_exit_limit_is_raised_to_clear_min_notional_when_the_bid_allows() -> None:
    # 0.05 BTC at ceil(100.40 * 0.995) = 99.90 is 4.995 < 5: the venue would refuse it. Selling at
    # 100.00 (still under the 100.40 bid) clears the minimum and fills at the bid all the same.
    w = world(FakeClient("A", Fill(0.05, 100.40)), FakeClient("B"))
    pos = Position("pos-x", "lag-1", "A", SYM, Side.BUY, 0.05, 100.00, 99.85, 100.50, T0, 30.0)
    rep = await w.engine.exit_position(pos, "target", q("A", 100.40, 100.41))
    assert w.a.requests[0].limit_price == 100.0
    assert rep.outcome is ExecutionOutcome.CLOSED and pos.qty == 0.0


async def test_position_below_min_notional_is_closed_as_dust_without_an_order() -> None:
    w = world(FakeClient("A"), FakeClient("B"))
    pos = Position("pos-x", "lag-1", "A", SYM, Side.BUY, 0.04, 100.00, 99.85, 100.50, T0, 30.0, entry_fee=0.004)
    rep = await w.engine.exit_position(pos, "time", q("A", 100.00, 100.01))  # 0.04 * 100 = $4 < $5
    assert w.a.requests == []
    assert rep.outcome is ExecutionOutcome.CLOSED and rep.residual_qty == pytest.approx(0.04)
    assert any("closed as dust" in n and "below the A min notional 5" in n for n in rep.notes)
    assert (pos.qty, pos.entry_fee) == (0.04, 0.004)  # kept for the caller's accounting


async def test_partial_exit_leaving_an_unsellable_remainder_closes_the_position_as_dust() -> None:
    w = world(FakeClient("A", Fill(0.46, 100.00)), FakeClient("B"))
    pos = Position("pos-x", "lag-1", "A", SYM, Side.BUY, 0.5, 100.00, 99.85, 100.50, T0, 30.0, entry_fee=0.05)
    rep = await w.engine.exit_position(pos, "time", q("A", 100.00, 100.01))
    assert rep.outcome is ExecutionOutcome.CLOSED  # 0.04 left: $4 can never be sold on its own
    assert pos.qty == pytest.approx(0.04, abs=ABS) and rep.residual_qty == pytest.approx(0.04, abs=ABS)
    assert rep.notes[0] == "closed (time) 0.46 @ 100"
    assert rep.realized_pnl == pytest.approx(0.0 - 0.046 - 0.046, abs=ABS)  # fee share + exit fee


class BaseFeeClient:
    """Fills everything at ``price`` and takes a BUY's 10 bps commission in the base asset, like Binance."""

    def __init__(self, venue: str, price: float) -> None:
        self.venue, self.price = venue, price
        self.requests: list[OrderRequest] = []

    async def place_ioc(self, req: OrderRequest) -> OrderResult:
        self.requests.append(req)
        base_fee = req.qty * 0.001 if req.side is Side.BUY else 0.0
        return OrderResult(req.client_id, req.venue, req.symbol, req.side, req.qty, req.qty, self.price,
                           req.qty * self.price * 0.001, OrderStatus.FILLED, T0, base_fee=base_fee)

    async def query_order(self, req: OrderRequest) -> OrderResult | None:
        return None


async def test_buy_with_commission_in_base_opens_and_exits_only_what_was_received() -> None:
    a = BaseFeeClient("A", 100.00)
    pf = Portfolio({"A": {"USDT": 1000.0}})
    engine = ExecutionEngine(make_cfg(venue("A", lot=0.00001), venue("B")), {"A": a, "B": FakeClient("B")}, pf,
                             default_book(), SimClock(T0))
    rep, pos = await engine.enter(lag_signal("A", Side.BUY, 100.00, stop=99.85, target=100.50), 1.0)
    assert pos is not None and pos.qty == pytest.approx(0.999)
    assert pf.balance("A", "BTC") == pytest.approx(0.999)  # the account received 0.999
    assert pf.balance("A", "USDT") == pytest.approx(1000.0 - 100.0)  # the fee was not paid in USDT
    assert any("commission of 0.001 paid in base" in n for n in rep.notes)
    out = await engine.exit_position(pos, "target", q("A", 100.50, 100.51))
    assert a.requests[1].qty == 0.999  # never more than the account holds
    assert out.outcome is ExecutionOutcome.CLOSED
    assert pf.balance("A", "BTC") == pytest.approx(0.0, abs=1e-12)


async def test_arb_with_commission_in_base_is_not_an_unequal_fill() -> None:
    w = world(BaseFeeClient("A", 100.00), BaseFeeClient("B", 100.30))  # type: ignore[arg-type]
    rep = await w.engine.execute(arb_signal(), 1.0)
    assert rep.outcome is ExecutionOutcome.COMPLETED and len(rep.orders) == 2  # no hedge of the fee
    assert w.pf.balance("A", "BTC") == pytest.approx(0.999)  # but the portfolio holds what was received
