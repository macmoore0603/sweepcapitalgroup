"""Tests for arbbot.execution.paper: IOC fills against the book as of order arrival.

Expected numbers are worked out by hand. Default venue A: taker fee 10 bps,
slippage 1 bps, latency 50 ms, BTC-USDT tick 0.01, lot 0.001. Orders are sent
at T0 = 1000.0 on a SimClock, so they arrive at 1000.05.
"""

from __future__ import annotations

import asyncio

import pytest

from arbbot.clock import SimClock
from arbbot.config import InstrumentConfig, VenueConfig
from arbbot.execution.base import ExchangeClient
from arbbot.execution.paper import (
    PaperExchange,
    realtime_sleep_until,
    simclock_sleep_until,
)
from arbbot.models import OrderRequest, OrderResult, OrderStatus, Quote, Side
from arbbot.portfolio import Portfolio

SYM = "BTC-USDT"
T0 = 1000.0


def venue(name: str = "A", *, fee: float = 10.0, slip: float = 1.0, latency_ms: float = 50.0,
          lot: float = 0.001, tick: float = 0.01) -> VenueConfig:
    return VenueConfig(
        name=name,
        feed="binance",
        taker_fee_bps=fee,
        slippage_bps=slip,
        latency_ms=latency_ms,
        instruments=(InstrumentConfig(symbol=SYM, venue_symbol="BTCUSDT", tick_size=tick, lot_size=lot),),
    )


def quote(venue_name: str = "A", bid: float = 99.99, ask: float = 100.00, *, bid_size: float = 2.0,
          ask_size: float = 2.0, ts: float = T0) -> Quote:
    return Quote(venue_name, SYM, bid, bid_size, ask, ask_size, ts_local=ts)


class TimedBook:
    """Time-indexed fake ``book_at``: the latest quote whose start time is <= t. Records every call."""

    def __init__(self, *timeline: tuple[float, Quote | None]) -> None:
        self.timeline = sorted(timeline, key=lambda x: x[0])
        self.calls: list[tuple[str, float]] = []

    def __call__(self, symbol: str, t: float) -> Quote | None:
        self.calls.append((symbol, t))
        current = None
        for start, q in self.timeline:
            if start <= t:
                current = q
        return current


def make(q: Quote | None = None, *, v: VenueConfig | None = None, fill_ratio: float = 1.0,
         book: TimedBook | None = None, clock: SimClock | None = None) -> tuple[PaperExchange, SimClock, TimedBook]:
    clock = clock or SimClock(T0)
    book = book or TimedBook((0.0, q))
    ex = PaperExchange(v or venue(), book, clock, sleep_until=simclock_sleep_until(clock), fill_ratio=fill_ratio)
    return ex, clock, book


def buy(qty: float = 1.0, limit: float = 100.05, cid: str = "o-1", venue_name: str = "A") -> OrderRequest:
    return OrderRequest(cid, venue_name, SYM, Side.BUY, qty, limit)


def sell(qty: float = 1.0, limit: float = 100.25, cid: str = "o-1", venue_name: str = "A") -> OrderRequest:
    return OrderRequest(cid, venue_name, SYM, Side.SELL, qty, limit)


def test_paper_exchange_is_an_exchange_client() -> None:
    ex, _, _ = make(quote())
    client: ExchangeClient = ex
    assert client.venue == "A"


# --------------------------------------------------------------------------- BUY


async def test_buy_fills_at_ask_plus_slippage_with_fee() -> None:
    ex, _, _ = make(quote(ask=100.00, ask_size=2.0))
    res = await ex.place_ioc(buy(1.0, 100.05))
    assert res.status is OrderStatus.FILLED
    assert res.filled_qty == 1.0
    assert res.requested_qty == 1.0
    assert res.avg_price == pytest.approx(100.01, abs=1e-9)  # 100.00 * (1 + 1 bps)
    assert res.fee == pytest.approx(0.10001, abs=1e-12)  # 1.0 * 100.01 * 10 bps
    assert (res.client_id, res.venue, res.symbol, res.side) == ("o-1", "A", SYM, Side.BUY)
    assert res.error is None
    assert res.ts == pytest.approx(T0 + 0.05)


async def test_buy_partial_fill_is_capped_by_displayed_size() -> None:
    ex, _, _ = make(quote(ask=100.00, ask_size=0.4))
    res = await ex.place_ioc(buy(1.0, 100.05))
    assert res.status is OrderStatus.PARTIALLY_FILLED
    assert res.filled_qty == 0.4
    assert res.remaining_qty == pytest.approx(0.6)
    assert res.avg_price == pytest.approx(100.01, abs=1e-9)
    assert res.fee == pytest.approx(0.040004, abs=1e-12)  # 0.4 * 100.01 * 10 bps


async def test_buy_expires_when_ask_above_limit() -> None:
    ex, _, _ = make(quote(bid=100.05, ask=100.06))
    res = await ex.place_ioc(buy(1.0, 100.05))
    assert res.status is OrderStatus.EXPIRED
    assert (res.filled_qty, res.avg_price, res.fee) == (0.0, 0.0, 0.0)


async def test_buy_fills_when_ask_equals_limit_and_price_is_capped_at_limit() -> None:
    ex, _, _ = make(quote(bid=100.04, ask=100.05))
    res = await ex.place_ioc(buy(1.0, 100.05))
    assert res.status is OrderStatus.FILLED
    assert res.avg_price == 100.05  # 100.05 * 1.0001 > limit -> capped at the limit


async def test_buy_slippage_is_capped_at_limit() -> None:
    ex, _, _ = make(quote(bid=100.03, ask=100.04), v=venue(slip=5.0))
    res = await ex.place_ioc(buy(1.0, 100.05))
    # 100.04 * (1 + 5 bps) = 100.09002 > 100.05 -> the limit is the worst price
    assert res.avg_price == 100.05
    assert res.fee == pytest.approx(0.10005, abs=1e-12)


async def test_fill_ratio_scales_displayed_size() -> None:
    ex, _, _ = make(quote(ask=100.00, ask_size=1.0), fill_ratio=0.5)
    res = await ex.place_ioc(buy(1.0, 100.05))
    assert res.status is OrderStatus.PARTIALLY_FILLED
    assert res.filled_qty == 0.5


async def test_fill_ratio_product_lands_on_the_lot_grid() -> None:
    # 0.7 * 0.1 is 0.06999999999999999 in floats; the fill must still be 0.07, not 0.069
    ex, _, _ = make(quote(ask=100.00, ask_size=0.7), fill_ratio=0.1)
    res = await ex.place_ioc(buy(1.0, 100.05))
    assert res.filled_qty == 0.07


async def test_fill_ratio_zero_never_fills_and_out_of_range_is_refused() -> None:
    ex, _, _ = make(quote(), fill_ratio=0.0)
    assert (await ex.place_ioc(buy())).status is OrderStatus.EXPIRED
    with pytest.raises(ValueError):
        make(quote(), fill_ratio=1.5)


async def test_fill_is_floored_to_lot() -> None:
    ex, _, _ = make(quote(ask=100.00, ask_size=0.12345))
    res = await ex.place_ioc(buy(1.0, 100.05))
    assert res.filled_qty == 0.123
    assert res.fee == pytest.approx(0.123 * 100.01 * 0.001, abs=1e-12)


async def test_available_below_one_lot_expires() -> None:
    ex, _, _ = make(quote(ask=100.00, ask_size=0.0009))
    res = await ex.place_ioc(buy(1.0, 100.05))
    assert res.status is OrderStatus.EXPIRED
    assert res.filled_qty == 0.0


# --------------------------------------------------------------------------- SELL


async def test_sell_fills_at_bid_minus_slippage_with_fee() -> None:
    ex, _, _ = make(quote(bid=100.30, ask=100.31, bid_size=2.0))
    res = await ex.place_ioc(sell(1.0, 100.25))
    assert res.status is OrderStatus.FILLED
    assert res.filled_qty == 1.0
    assert res.avg_price == pytest.approx(100.28997, abs=1e-9)  # 100.30 * (1 - 1 bps)
    assert res.fee == pytest.approx(0.10028997, abs=1e-12)


async def test_sell_partial_and_expired_and_capped() -> None:
    ex, _, _ = make(quote(bid=100.30, ask=100.31, bid_size=0.3))
    res = await ex.place_ioc(sell(1.0, 100.25))
    assert (res.status, res.filled_qty) == (OrderStatus.PARTIALLY_FILLED, 0.3)

    ex, _, _ = make(quote(bid=100.24, ask=100.25))
    res = await ex.place_ioc(sell(1.0, 100.25))
    assert (res.status, res.filled_qty, res.avg_price) == (OrderStatus.EXPIRED, 0.0, 0.0)

    ex, _, _ = make(quote(bid=100.26, ask=100.27), v=venue(slip=5.0))
    res = await ex.place_ioc(sell(1.0, 100.25))
    assert res.avg_price == 100.25  # 100.26 * (1 - 5 bps) = 100.20987 < limit -> capped


# --------------------------------------------------------------------------- no / bad data


async def test_no_quote_expires() -> None:
    ex, _, _ = make(None)
    res = await ex.place_ioc(buy())
    assert res.status is OrderStatus.EXPIRED
    assert res.filled_qty == 0.0
    assert res.error == "no quote"


async def test_invalid_quote_expires() -> None:
    crossed = quote(bid=100.10, ask=100.00)
    ex, _, _ = make(crossed)
    assert (await ex.place_ioc(buy())).status is OrderStatus.EXPIRED
    ex, _, _ = make(quote(ask_size=0.0))
    assert (await ex.place_ioc(buy())).status is OrderStatus.EXPIRED


async def test_malformed_requests_are_rejected_and_not_stored() -> None:
    ex, _, _ = make(quote())
    wrong_venue = await ex.place_ioc(buy(cid="w", venue_name="B"))
    assert wrong_venue.status is OrderStatus.REJECTED
    unknown_symbol = await ex.place_ioc(OrderRequest("u", "A", "ETH-USDT", Side.BUY, 1.0, 100.0))
    assert unknown_symbol.status is OrderStatus.REJECTED
    zero_qty = await ex.place_ioc(buy(0.0, cid="z"))
    assert zero_qty.status is OrderStatus.REJECTED
    assert zero_qty.filled_qty == 0.0
    for cid in ("w", "u", "z"):
        assert await ex.query_order(buy(cid=cid)) is None


# --------------------------------------------------------------------------- query_order


async def test_query_order_returns_stored_result() -> None:
    ex, _, _ = make(quote(ask_size=0.4))
    req = buy(1.0, 100.05, cid="abc")
    res = await ex.place_ioc(req)
    assert await ex.query_order(req) == res
    expired = await ex.place_ioc(buy(1.0, 99.0, cid="exp"))
    assert expired.status is OrderStatus.EXPIRED
    assert await ex.query_order(buy(cid="exp")) == expired
    assert await ex.query_order(buy(cid="never-sent")) is None


async def test_duplicate_client_id_is_rejected_and_keeps_the_original() -> None:
    ex, _, _ = make(quote())
    first = await ex.place_ioc(buy(1.0, cid="dup"))
    second = await ex.place_ioc(buy(0.5, cid="dup"))
    assert first.status is OrderStatus.FILLED
    assert second.status is OrderStatus.REJECTED
    assert await ex.query_order(buy(cid="dup")) == first


# --------------------------------------------------------------------------- arrival time


async def test_fill_uses_the_book_as_of_arrival_not_send_time() -> None:
    # At send time (T0) the ask is 100.00 (fillable); by arrival (T0 + 50 ms) it is 100.10.
    book = TimedBook((0.0, quote(ask=100.00)), (T0 + 0.03, quote(bid=100.09, ask=100.10)))
    ex, clock, book = make(book=book)
    res = await ex.place_ioc(buy(1.0, 100.05))
    assert book.calls == [(SYM, pytest.approx(T0 + 0.05))]
    assert res.status is OrderStatus.EXPIRED
    assert clock.now() == pytest.approx(T0 + 0.05)  # the backtest clock jumped to arrival
    assert res.ts == pytest.approx(T0 + 0.05)


async def test_arrival_book_can_also_be_better() -> None:
    book = TimedBook((0.0, quote(ask=100.00)), (T0 + 0.04, quote(bid=99.89, ask=99.90)))
    ex, _, _ = make(book=book)
    res = await ex.place_ioc(buy(1.0, 100.05))
    assert res.avg_price == pytest.approx(99.90 * 1.0001, abs=1e-9)


async def test_concurrent_legs_share_the_send_time_and_see_their_own_arrival_books() -> None:
    clock = SimClock(T0)
    a_book = TimedBook((0.0, quote("A", 99.99, 100.00)))
    # B's bid collapses at T0 + 0.21: a leg arriving at T0 + 0.2 fills, one arriving at T0 + 0.25 does not.
    b_book = TimedBook((0.0, quote("B", 100.30, 100.31)), (T0 + 0.21, quote("B", 100.10, 100.11)))
    sleep = simclock_sleep_until(clock)
    a = PaperExchange(venue("A", latency_ms=50.0), a_book, clock, sleep_until=sleep)
    b = PaperExchange(venue("B", latency_ms=200.0), b_book, clock, sleep_until=sleep)

    ra, rb = await asyncio.gather(
        a.place_ioc(buy(1.0, 100.05, cid="a1", venue_name="A")),
        b.place_ioc(sell(1.0, 100.25, cid="b1", venue_name="B")),
    )
    assert a_book.calls == [(SYM, pytest.approx(T0 + 0.05))]
    assert b_book.calls == [(SYM, pytest.approx(T0 + 0.2))]  # not T0 + 0.05 + 0.2
    assert ra.status is OrderStatus.FILLED and rb.status is OrderStatus.FILLED
    assert rb.avg_price == pytest.approx(100.30 * 0.9999, abs=1e-9)
    assert clock.now() == pytest.approx(T0 + 0.2)


async def test_sequential_orders_are_sent_after_the_clock_advanced() -> None:
    # Contrast with the concurrent case: a second order sent after the first returns leaves later.
    clock = SimClock(T0)
    a_book = TimedBook((0.0, quote("A", 99.99, 100.00)))
    b_book = TimedBook((0.0, quote("B", 100.30, 100.31)), (T0 + 0.21, quote("B", 100.10, 100.11)))
    sleep = simclock_sleep_until(clock)
    a = PaperExchange(venue("A", latency_ms=50.0), a_book, clock, sleep_until=sleep)
    b = PaperExchange(venue("B", latency_ms=200.0), b_book, clock, sleep_until=sleep)
    await a.place_ioc(buy(1.0, 100.05, cid="a1", venue_name="A"))
    rb = await b.place_ioc(sell(1.0, 100.25, cid="b1", venue_name="B"))
    assert b_book.calls == [(SYM, pytest.approx(T0 + 0.25))]
    assert rb.status is OrderStatus.EXPIRED


async def test_simclock_sleep_until_never_moves_backwards() -> None:
    clock = SimClock(5.0)
    sleep = simclock_sleep_until(clock)
    await sleep(3.0)
    assert clock.now() == 5.0
    await sleep(7.5)
    assert clock.now() == 7.5


async def test_realtime_sleep_until_waits_for_the_clock() -> None:
    class Fixed:
        def now(self) -> float:
            return 100.0

    loop = asyncio.get_running_loop()
    sleep = realtime_sleep_until(Fixed())
    t = loop.time()
    await sleep(100.03)
    assert loop.time() - t >= 0.025
    t = loop.time()
    await sleep(99.0)  # already past: no wait
    assert loop.time() - t < 0.02


async def test_result_type() -> None:
    ex, _, _ = make(quote())
    assert isinstance(await ex.place_ioc(buy()), OrderResult)


# --------------------------------------------------------------------------- review findings (regressions)


async def test_liquidity_taken_from_a_quote_is_not_offered_again() -> None:
    ex, _, _ = make(quote(ask=100.00, ask_size=1.5, bid=99.99, bid_size=0.5))
    fills = [(await ex.place_ioc(buy(1.0, 100.05, cid=f"b{i}"))).filled_qty for i in range(3)]
    assert fills == [1.0, 0.5, 0.0]  # 1.5 displayed in total, not 1.5 per order
    # The bid is a separate level.
    sells = [(await ex.place_ioc(sell(1.0, 99.0, cid=f"s{i}"))).filled_qty for i in range(2)]
    assert sells == [0.5, 0.0]


async def test_taken_liquidity_respects_the_fill_ratio() -> None:
    ex, _, _ = make(quote(ask=100.00, ask_size=2.0), fill_ratio=0.5)
    first = await ex.place_ioc(buy(0.6, 100.05, cid="1"))
    second = await ex.place_ioc(buy(1.0, 100.05, cid="2"))
    assert (first.filled_qty, second.filled_qty) == (0.6, 0.4)  # 2.0 * 0.5 takeable in total


async def test_a_newer_quote_replaces_the_taken_level() -> None:
    q1, q2 = quote(ask_size=1.0, ts=T0), quote(ask_size=1.0, ts=T0 + 0.07)
    ex, _, _ = make(book=TimedBook((0.0, q1), (T0 + 0.07, q2)))
    r1 = await ex.place_ioc(buy(1.0, cid="1"))  # arrives T0 + 0.05: q1
    r2 = await ex.place_ioc(buy(1.0, cid="2"))  # sent T0 + 0.05, arrives T0 + 0.10: q2, a fresh level
    assert (r1.filled_qty, r2.filled_qty) == (1.0, 1.0)


async def test_order_below_min_notional_is_rejected_like_the_venue() -> None:
    ex, _, _ = make(quote())  # min_notional 5.0 (the InstrumentConfig default)
    tiny = await ex.place_ioc(buy(0.04, 100.05, cid="tiny"))  # 0.04 * 100.05 = 4.002 < 5
    assert tiny.status is OrderStatus.REJECTED and tiny.filled_qty == 0.0
    assert "Filter failure: NOTIONAL" in (tiny.error or "")
    assert await ex.query_order(buy(cid="tiny")) is None  # the venue keeps no record
    edge = await ex.place_ioc(buy(0.05, 100.00, cid="edge"))  # exactly 5.0 at the limit
    assert edge.status is OrderStatus.FILLED


async def test_with_a_portfolio_orders_the_balance_cannot_cover_are_rejected() -> None:
    pf = Portfolio({"A": {"USDT": 100.0, "BTC": 0.5}})
    clock = SimClock(T0)
    ex = PaperExchange(venue(), TimedBook((0.0, quote(bid_size=5.0, ask_size=5.0))), clock,
                       sleep_until=simclock_sleep_until(clock), portfolio=pf)
    over_sell = await ex.place_ioc(sell(0.6, 99.0, cid="s1"))  # holds 0.5 BTC: spot cannot short
    assert over_sell.status is OrderStatus.REJECTED and "insufficient balance" in (over_sell.error or "")
    assert (await ex.place_ioc(sell(0.5, 99.0, cid="s2"))).status is OrderStatus.FILLED
    over_buy = await ex.place_ioc(buy(1.0, 100.05, cid="b1"))  # needs 100.05 USDT at the limit
    assert over_buy.status is OrderStatus.REJECTED
    assert (await ex.place_ioc(buy(0.99, 100.05, cid="b2"))).status is OrderStatus.FILLED  # 99.0495
    assert pf.snapshot() == {"A": {"USDT": 100.0, "BTC": 0.5}}  # the venue never changes balances
