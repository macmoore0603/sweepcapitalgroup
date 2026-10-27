"""Tests for arbbot.execution.monitor.PositionMonitor.

The engine is a fake implementing ``exit_position`` as DESIGN.md specifies:
an IOC for the open qty on the opposite side; a partial fill reduces
``position.qty`` and increments ``exit_attempts``; a full fill returns CLOSED.
Fills are scripted per call as absolute base quantities so every expected
number below is exact.

Default long: BUY 2.0 BTC-USDT on venue "lag" at 100.0, stop 99.0, target
101.0, opened at T0=1000, max_hold 30 s. Default short: SELL 2.0 at 100.0,
stop 101.0, target 99.0. Quotes go stale after 1.5 s (default risk config).
"""

from __future__ import annotations

import asyncio

import pytest

from arbbot.clock import SimClock
from arbbot.config import BotConfig, InstrumentConfig, VenueConfig
from arbbot.execution.monitor import PositionMonitor, exit_reason
from arbbot.feeds.base import QuoteBook
from arbbot.models import ExecutionOutcome, ExecutionReport, Position, Quote, Side

SYM = "BTC-USDT"
VENUE = "lag"
T0 = 1000.0


def make_cfg() -> BotConfig:
    inst = InstrumentConfig(symbol=SYM, venue_symbol="BTCUSDT", lot_size=0.001)
    return BotConfig(venues=(VenueConfig(name=VENUE, feed="binance", taker_fee_bps=10.0, instruments=(inst,)),))


def long_pos(pid: str = "pos-1", qty: float = 2.0) -> Position:
    return Position(id=pid, signal_id=f"sig-{pid}", venue=VENUE, symbol=SYM, side=Side.BUY, qty=qty,
                    entry_price=100.0, stop_price=99.0, target_price=101.0, opened_ts=T0, max_hold_s=30.0)


def short_pos(pid: str = "pos-s", qty: float = 2.0) -> Position:
    return Position(id=pid, signal_id=f"sig-{pid}", venue=VENUE, symbol=SYM, side=Side.SELL, qty=qty,
                    entry_price=100.0, stop_price=101.0, target_price=99.0, opened_ts=T0, max_hold_s=30.0)


def quote(bid: float, ask: float, ts: float, *, venue: str = VENUE, symbol: str = SYM) -> Quote:
    return Quote(venue=venue, symbol=symbol, bid=bid, bid_size=5.0, ask=ask, ask_size=5.0, ts_local=ts)


class FakeEngine:
    """Scripted ``exit_position``: each call fills the next scripted qty (default: everything)."""

    def __init__(self, fills: list[float] | None = None, *, outcome_on_fail: ExecutionOutcome | None = None,
                 count_no_fill: bool = True) -> None:
        self.fills = list(fills or [])
        self.calls: list[tuple[str, str, float, Quote]] = []  # (position id, reason, qty before, quote)
        self.outcome_on_fail = outcome_on_fail
        self.count_no_fill = count_no_fill
        self.gate: asyncio.Event | None = None
        self.raise_exc: Exception | None = None

    async def exit_position(self, position: Position, reason: str, quote: Quote) -> ExecutionReport:
        self.calls.append((position.id, reason, position.qty, quote))
        if self.gate is not None:
            await self.gate.wait()
        if self.raise_exc is not None:
            raise self.raise_exc
        filled = self.fills.pop(0) if self.fills else position.qty
        exit_price = quote.price_for(position.side.opposite())
        pnl = position.side.sign * filled * (exit_price - position.entry_price)
        if filled >= position.qty:
            position.qty = 0.0
            return ExecutionReport(signal_id=position.signal_id, outcome=ExecutionOutcome.CLOSED,
                                   realized_pnl=pnl, position_id=position.id, notes=[reason])
        if self.outcome_on_fail is not None:
            return ExecutionReport(signal_id=position.signal_id, outcome=self.outcome_on_fail,
                                   position_id=position.id)
        position.qty -= filled
        if filled > 0 or self.count_no_fill:
            position.exit_attempts += 1
        outcome = ExecutionOutcome.FLATTENED if filled > 0 else ExecutionOutcome.NO_FILL
        return ExecutionReport(signal_id=position.signal_id, outcome=outcome, realized_pnl=pnl,
                               position_id=position.id, notes=[f"partial exit {filled}"])


def setup(fills: list[float] | None = None, *, start: float = T0, max_exit_attempts: int = 5, **kw):
    clock = SimClock(start)
    engine = FakeEngine(fills, **kw)
    mon = PositionMonitor(make_cfg(), engine, clock, max_exit_attempts=max_exit_attempts)
    return clock, engine, mon


# --------------------------------------------------------------------------- long exits


async def test_long_holds_between_stop_and_target():
    clock, engine, mon = setup()
    mon.open(long_pos())
    clock.set(T0 + 10)
    assert await mon.on_quote(quote(99.5, 99.6, T0 + 10)) == []
    assert engine.calls == []
    assert [p.id for p in mon.positions] == ["pos-1"]


async def test_long_stop_exits_at_bid_equal_to_stop_and_removes_position():
    clock, engine, mon = setup()
    mon.open(long_pos())
    clock.set(T0 + 1)
    q = quote(99.0, 99.1, T0 + 1)
    reports = await mon.on_quote(q)
    assert engine.calls == [("pos-1", "stop", 2.0, q)]
    assert len(reports) == 1 and reports[0].outcome is ExecutionOutcome.CLOSED
    assert reports[0].realized_pnl == pytest.approx(2.0 * (99.0 - 100.0))  # -2.0
    assert mon.positions == ()
    # A closed position never exits again.
    assert await mon.on_quote(quote(98.0, 98.1, T0 + 2)) == []
    assert len(engine.calls) == 1


async def test_long_target_exits_at_bid_reaching_target():
    clock, engine, mon = setup()
    mon.open(long_pos())
    clock.set(T0 + 2)
    q = quote(101.0, 101.1, T0 + 2)
    reports = await mon.on_quote(q)
    assert engine.calls == [("pos-1", "target", 2.0, q)]
    assert reports[0].outcome is ExecutionOutcome.CLOSED
    assert reports[0].realized_pnl == pytest.approx(2.0)
    assert mon.positions == ()


async def test_long_time_stop_exactly_at_max_hold():
    clock, engine, mon = setup()
    mon.open(long_pos())
    clock.set(T0 + 29.9)
    assert await mon.on_quote(quote(100.0, 100.1, T0 + 29.9)) == []
    clock.set(T0 + 30.0)
    q = quote(100.0, 100.1, T0 + 30.0)
    reports = await mon.on_quote(q)
    assert engine.calls == [("pos-1", "time", 2.0, q)]
    assert reports[0].outcome is ExecutionOutcome.CLOSED
    assert mon.positions == ()


async def test_stop_takes_precedence_over_elapsed_time_stop():
    clock, engine, mon = setup()
    mon.open(long_pos())
    clock.set(T0 + 45)
    await mon.on_quote(quote(98.5, 98.6, T0 + 45))
    assert engine.calls[0][1] == "stop"


# --------------------------------------------------------------------------- short exits


async def test_short_stop_on_ask_at_or_above_stop():
    clock, engine, mon = setup()
    mon.open(short_pos())
    clock.set(T0 + 1)
    assert await mon.on_quote(quote(100.8, 100.9, T0 + 1)) == []  # ask below stop, above target
    q = quote(100.9, 101.0, T0 + 1.5)
    reports = await mon.on_quote(q)
    assert engine.calls == [("pos-s", "stop", 2.0, q)]
    # Short: bought back at ask 101.0 -> -1 * 2.0 * (101.0 - 100.0) = -2.0
    assert reports[0].realized_pnl == pytest.approx(-2.0)
    assert mon.positions == ()


async def test_short_target_on_ask_at_or_below_target():
    clock, engine, mon = setup()
    mon.open(short_pos())
    clock.set(T0 + 3)
    q = quote(98.9, 99.0, T0 + 3)
    reports = await mon.on_quote(q)
    assert engine.calls == [("pos-s", "target", 2.0, q)]
    assert reports[0].realized_pnl == pytest.approx(2.0)


async def test_short_time_stop():
    clock, engine, mon = setup()
    mon.open(short_pos())
    clock.set(T0 + 31)
    q = quote(99.9, 100.0, T0 + 31)
    await mon.on_quote(q)
    assert engine.calls == [("pos-s", "time", 2.0, q)]


def test_exit_reason_is_pure_and_mirrored():
    lp, sp = long_pos(), short_pos()
    assert exit_reason(lp, quote(99.0, 99.2, T0), T0) == "stop"
    assert exit_reason(lp, quote(101.0, 101.2, T0), T0) == "target"
    assert exit_reason(lp, quote(100.0, 100.2, T0), T0 + 30) == "time"
    assert exit_reason(lp, quote(100.0, 100.2, T0), T0 + 29.99) is None
    # The short side looks at the ask: a bid at the long stop means nothing to it.
    assert exit_reason(sp, quote(99.0, 99.2, T0), T0) is None
    assert exit_reason(sp, quote(100.8, 101.0, T0), T0) == "stop"
    assert exit_reason(sp, quote(98.8, 99.0, T0), T0) == "target"
    assert exit_reason(sp, quote(99.5, 99.7, T0), T0 + 30) == "time"


# --------------------------------------------------------------------------- never blocked


async def test_exit_uses_latest_quote_even_if_stale():
    clock, engine, mon = setup()
    mon.open(long_pos())
    clock.set(T0 + 500)  # the quote below is 499 s old, far beyond max_quote_age_ms=1500
    q = quote(98.0, 98.1, T0 + 1)
    reports = await mon.on_quote(q)
    assert engine.calls == [("pos-1", "stop", 2.0, q)]
    assert reports[0].outcome is ExecutionOutcome.CLOSED
    assert any("stale quote" in n for n in reports[0].notes)


async def test_out_of_order_quote_does_not_replace_newer_one():
    clock, engine, mon = setup()
    mon.open(long_pos())
    clock.set(T0 + 31)
    newer = quote(100.0, 100.1, T0 + 5)
    reports = await mon.on_quote(newer)  # time stop: exits at the newest quote
    assert engine.calls == [("pos-1", "time", 2.0, newer)]
    assert reports[0].outcome is ExecutionOutcome.CLOSED
    # Second position: an older quote arriving after a newer one is priced from the newer one.
    mon.open(long_pos("pos-2"))
    older = quote(98.0, 98.1, T0 + 3)  # would look like a stop, but it predates `newer`
    await mon.on_quote(older)
    assert engine.calls[1] == ("pos-2", "time", 2.0, newer)


async def test_on_tick_time_stop_without_new_quotes_uses_book_quote():
    clock, engine, mon = setup()
    mon.open(long_pos())
    book = QuoteBook()
    q = quote(100.0, 100.1, T0 + 1)
    book.update(q)
    clock.set(T0 + 29)
    assert await mon.on_tick(book) == []
    clock.set(T0 + 31)
    reports = await mon.on_tick(book)
    assert engine.calls == [("pos-1", "time", 2.0, q)]
    assert reports[0].outcome is ExecutionOutcome.CLOSED
    assert mon.positions == ()


async def test_on_tick_falls_back_to_monitor_cache_after_venue_invalidated():
    clock, engine, mon = setup()
    mon.open(long_pos())
    book = QuoteBook()
    q = quote(100.0, 100.1, T0 + 2)
    book.update(q)
    assert await mon.on_quote(q) == []
    book.invalidate_venue(VENUE)  # feed disconnected: the book forgets the venue
    clock.set(T0 + 40)
    reports = await mon.on_tick(book)
    assert engine.calls == [("pos-1", "time", 2.0, q)]
    assert reports[0].outcome is ExecutionOutcome.CLOSED


async def test_on_tick_prefers_newer_of_book_and_cache():
    clock, engine, mon = setup()
    mon.open(long_pos())
    old = quote(100.0, 100.1, T0 + 1)
    await mon.on_quote(old)
    book = QuoteBook()
    newer = quote(100.2, 100.3, T0 + 5)
    book.update(newer)
    clock.set(T0 + 30)
    await mon.on_tick(book)
    assert engine.calls[0][3] is newer


async def test_on_tick_without_any_quote_does_nothing():
    clock, engine, mon = setup()
    mon.open(long_pos())
    clock.set(T0 + 100)
    assert await mon.on_tick(QuoteBook()) == []
    assert engine.calls == []
    assert [p.id for p in mon.positions] == ["pos-1"]


async def test_invalid_and_unrelated_quotes_are_ignored():
    clock, engine, mon = setup()
    mon.open(long_pos())
    clock.set(T0 + 1)
    assert await mon.on_quote(quote(98.0, 97.0, T0 + 1)) == []  # crossed: a data glitch
    assert await mon.on_quote(quote(90.0, 90.1, T0 + 1, venue="other")) == []
    assert await mon.on_quote(quote(90.0, 90.1, T0 + 1, symbol="ETH-USDT")) == []
    assert engine.calls == []


# --------------------------------------------------------------------------- partial exits / residual


async def test_partial_exit_keeps_position_and_retries_on_next_quote():
    clock, engine, mon = setup(fills=[0.5])
    pos = long_pos()
    mon.open(pos)
    clock.set(T0 + 1)
    q1 = quote(99.0, 99.1, T0 + 1)
    r1 = await mon.on_quote(q1)
    assert [r.outcome for r in r1] == [ExecutionOutcome.FLATTENED]
    assert pos.qty == pytest.approx(1.5) and pos.exit_attempts == 1
    assert [p.id for p in mon.positions] == ["pos-1"]
    assert mon.exiting("pos-1") == "stop"
    # The price recovered above the stop, but the exit already started: retry anyway.
    clock.set(T0 + 2)
    q2 = quote(99.6, 99.7, T0 + 2)
    r2 = await mon.on_quote(q2)
    assert engine.calls == [("pos-1", "stop", 2.0, q1), ("pos-1", "stop", 1.5, q2)]
    assert [r.outcome for r in r2] == [ExecutionOutcome.CLOSED]
    assert mon.positions == ()
    assert mon.exiting("pos-1") is None


async def test_residual_after_max_exit_attempts_long():
    clock, engine, mon = setup(fills=[0.5, 0.5, 0.5], max_exit_attempts=3)
    pos = long_pos()
    mon.open(pos)
    outcomes = []
    for i in range(3):
        clock.set(T0 + 1 + i)
        reports = await mon.on_quote(quote(98.9, 99.1, T0 + 1 + i))
        outcomes.append([r.outcome for r in reports])
    assert outcomes == [
        [ExecutionOutcome.FLATTENED],
        [ExecutionOutcome.FLATTENED],
        [ExecutionOutcome.FLATTENED, ExecutionOutcome.RESIDUAL],
    ]
    assert len(engine.calls) == 3  # the engine's exit_attempts increments are not double counted
    residual = reports[-1]
    assert residual.signal_id == "sig-pos-1" and residual.position_id == "pos-1"
    assert residual.residual_qty == pytest.approx(0.5)  # 2.0 - 3 * 0.5, long -> positive
    assert residual.realized_pnl == pytest.approx(0.5 * (99.0 - 100.0))  # marked to mid 99.0
    assert residual.started_ts == T0 + 3 and residual.finished_ts == T0 + 3
    assert any("3 attempts" in n for n in residual.notes)
    assert mon.positions == ()
    assert [p.id for p in mon.residuals] == ["pos-1"]
    # No further exits once the operator owns it.
    assert await mon.on_quote(quote(98.0, 98.2, T0 + 10)) == []
    assert len(engine.calls) == 3


async def test_residual_short_is_negative_and_counts_no_fill_attempts_itself():
    # This engine does not bump exit_attempts on a zero fill; the monitor counts calls itself.
    clock, _engine, mon = setup(fills=[0.0, 0.0], max_exit_attempts=2, count_no_fill=False)
    pos = short_pos()
    mon.open(pos)
    clock.set(T0 + 1)
    r1 = await mon.on_quote(quote(100.9, 101.1, T0 + 1))
    assert [r.outcome for r in r1] == [ExecutionOutcome.NO_FILL]
    assert pos.exit_attempts == 0
    r2 = await mon.on_quote(quote(100.9, 101.1, T0 + 2))
    assert [r.outcome for r in r2] == [ExecutionOutcome.NO_FILL, ExecutionOutcome.RESIDUAL]
    assert r2[1].residual_qty == pytest.approx(-2.0)
    # Short marked at mid 101.0: -2.0 * (101.0 - 100.0) = -2.0
    assert r2[1].realized_pnl == pytest.approx(-2.0)
    assert mon.positions == () and [p.id for p in mon.residuals] == ["pos-s"]


async def test_residual_mark_is_net_of_remaining_entry_fee():
    # The engine books the entry fee pro rata on each close; what is still open carries the rest.
    clock, _engine, mon = setup(fills=[0.0], max_exit_attempts=1)
    pos = long_pos()
    pos.entry_fee = 0.2
    mon.open(pos)
    clock.set(T0 + 1)
    reports = await mon.on_quote(quote(98.9, 99.1, T0 + 1))
    residual = reports[-1]
    assert residual.outcome is ExecutionOutcome.RESIDUAL
    # 2.0 * (mid 99.0 - entry 100.0) - remaining entry fee 0.2 = -2.2
    assert residual.realized_pnl == pytest.approx(-2.2)
    assert residual.fees == 0.0  # the entry fee itself was already reported by the OPENED report


async def test_on_tick_retries_pending_exit_only_with_a_newer_quote():
    clock, engine, mon = setup(fills=[0.5])
    mon.open(long_pos())
    book = QuoteBook()
    q1 = quote(99.0, 99.1, T0 + 1)
    book.update(q1)
    clock.set(T0 + 1)
    await mon.on_quote(q1)
    assert len(engine.calls) == 1
    clock.set(T0 + 2)
    assert await mon.on_tick(book) == []  # same quote as the failed attempt: wait
    assert len(engine.calls) == 1
    q2 = quote(99.2, 99.3, T0 + 2)
    book.update(q2)
    reports = await mon.on_tick(book)
    assert engine.calls[1] == ("pos-1", "stop", 1.5, q2)
    assert [r.outcome for r in reports] == [ExecutionOutcome.CLOSED]


async def test_unknown_exit_parks_position_without_retrying():
    clock, engine, mon = setup(fills=[0.0], outcome_on_fail=ExecutionOutcome.UNKNOWN)
    mon.open(long_pos())
    clock.set(T0 + 1)
    reports = await mon.on_quote(quote(98.0, 98.1, T0 + 1))
    assert [r.outcome for r in reports] == [ExecutionOutcome.UNKNOWN]
    assert mon.positions == () and [p.id for p in mon.unresolved] == ["pos-1"]
    assert await mon.on_quote(quote(97.0, 97.1, T0 + 2)) == []
    assert len(engine.calls) == 1


async def test_engine_exception_becomes_unknown_report():
    clock, engine, mon = setup()
    engine.raise_exc = RuntimeError("boom")
    mon.open(long_pos())
    clock.set(T0 + 1)
    reports = await mon.on_quote(quote(98.0, 98.1, T0 + 1))
    assert len(reports) == 1
    r = reports[0]
    assert r.outcome is ExecutionOutcome.UNKNOWN and r.position_id == "pos-1" and r.signal_id == "sig-pos-1"
    assert any("RuntimeError: boom" in n for n in r.notes)
    assert [p.id for p in mon.unresolved] == ["pos-1"]


async def test_concurrent_events_do_not_double_exit():
    clock, engine, mon = setup()
    engine.gate = asyncio.Event()
    mon.open(long_pos())
    book = QuoteBook()
    q = quote(98.0, 98.1, T0 + 1)
    book.update(q)
    clock.set(T0 + 1)
    first = asyncio.create_task(mon.on_quote(q))
    await asyncio.sleep(0)
    assert len(engine.calls) == 1
    assert await mon.on_tick(book) == []  # exit in flight: skipped
    assert await mon.on_quote(quote(97.0, 97.1, T0 + 2)) == []
    engine.gate.set()
    reports = await first
    assert [r.outcome for r in reports] == [ExecutionOutcome.CLOSED]
    assert len(engine.calls) == 1


async def test_multiple_positions_exit_in_open_order():
    clock, engine, mon = setup()
    mon.open(long_pos("a"))
    mon.open(long_pos("b", qty=1.0))
    mon.open(short_pos("c"))
    clock.set(T0 + 1)
    await mon.on_quote(quote(98.5, 98.6, T0 + 1))  # longs stop out; short (ask 98.6 <= 99) hits target
    assert [(c[0], c[1]) for c in engine.calls] == [("a", "stop"), ("b", "stop"), ("c", "target")]
    assert mon.positions == ()


def test_open_validates():
    _, _, mon = setup()
    mon.open(long_pos())
    with pytest.raises(ValueError):
        mon.open(long_pos())
    with pytest.raises(ValueError):
        mon.open(long_pos("z", qty=0.0))
    with pytest.raises(ValueError):
        PositionMonitor(make_cfg(), FakeEngine(), SimClock(T0), max_exit_attempts=0)
