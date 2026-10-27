"""Tests for arbbot.app.Bot: event order, disconnects, scan-only, in-flight limit, halts, live loop.

Default world: venues A and B list BTC-USDT and ETH-USDT (tick 0.01, lot 0.001),
10 bps taker, no slippage, no latency; each holds 10000 USDT, 1 BTC, 10 ETH.
Book: A 99.99/100.00, B 100.40/100.41 -> buy A sell B: gross 40 bps - 20 bps
fees = net 20 bps; size min(0.5 * 5, 500 / 100, ..., B's 1 BTC) = 1.0.
Orders go to PaperExchanges that fill from the bot's own QuoteBook.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest

from arbbot.app import IN_FLIGHT, Bot, portfolio_from_config
from arbbot.clock import SimClock
from arbbot.config import (
    BotConfig,
    InstrumentConfig,
    RiskConfig,
    SignalConfig,
    VenueConfig,
)
from arbbot.execution.paper import PaperExchange, simclock_sleep_until
from arbbot.feeds.base import QuoteBook
from arbbot.journal import Journal
from arbbot.models import (
    ExecutionOutcome,
    FeedEvent,
    FeedStatus,
    OrderRequest,
    OrderResult,
    OrderStatus,
    Position,
    Quote,
    Side,
)

BTC = "BTC-USDT"
ETH = "ETH-USDT"
T0 = 1000.0


def inst(symbol: str) -> InstrumentConfig:
    return InstrumentConfig(symbol, symbol.replace("-", ""), tick_size=0.01, lot_size=0.001, min_notional=1.0)


def make_cfg() -> BotConfig:
    bal = {"USDT": 10_000.0, "BTC": 1.0, "ETH": 10.0}
    venues = tuple(
        VenueConfig(name, feed, taker_fee_bps=10.0, slippage_bps=0.0, latency_ms=0.0,
                    instruments=(inst(BTC), inst(ETH)), starting_balances=dict(bal))
        for name, feed in (("A", "binance"), ("B", "bybit"))
    )
    return BotConfig(
        venues=venues,
        signal=SignalConfig(min_net_edge_bps=5.0, participation=0.5, cooldown_ms=0.0),
        risk=RiskConfig(min_top_depth_notional=100.0),
    )


def q(venue: str, bid: float, ask: float, t: float = T0, symbol: str = BTC, size: float = 5.0,
      seq: int | None = None) -> Quote:
    return Quote(venue, symbol, bid, size, ask, size, t, seq=seq)


class CaptureJournal(Journal):
    def __init__(self) -> None:
        super().__init__(None)
        self.records: list[tuple[str, float, Any]] = []

    def record(self, kind: str, ts: float, payload: Any) -> None:
        self.records.append((kind, ts, payload))

    def kinds(self) -> list[str]:
        return [k for k, _, _ in self.records]


class CaptureAlerter:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def send(self, text: str) -> None:
        self.texts.append(text)

    def close(self, timeout_s: float = 5.0) -> None:
        pass


class Spy:
    """Wraps a client: records requests, can hold them at a gate, can refuse one side."""

    def __init__(self, inner: PaperExchange, sent: list[OrderRequest], gate: asyncio.Event | None = None,
                 expire: Side | None = None):
        self.venue = inner.venue
        self.inner = inner
        self.sent = sent  # shared by every venue: the order requests were sent in
        self.gate = gate
        self.expire = expire

    async def place_ioc(self, req: OrderRequest) -> OrderResult:
        self.sent.append(req)
        if self.gate is not None:
            await self.gate.wait()
        if req.side is self.expire:
            return OrderResult(req.client_id, req.venue, req.symbol, req.side, req.qty, 0.0, 0.0, 0.0,
                               OrderStatus.EXPIRED, T0)
        return await self.inner.place_ioc(req)

    async def query_order(self, req: OrderRequest) -> OrderResult | None:
        return await self.inner.query_order(req)


class World:
    def __init__(self, *, clients: bool = True, inline: bool = True, gate: asyncio.Event | None = None,
                 cfg: BotConfig | None = None, expire: dict[str, Side] | None = None,
                 fill_ratio: dict[str, float] | None = None) -> None:
        self.cfg = cfg or make_cfg()
        self.clock = SimClock(T0)
        self.book = QuoteBook()
        self.journal = CaptureJournal()
        self.alerter = CaptureAlerter()
        self.spies: dict[str, Spy] = {}
        self.sent: list[OrderRequest] = []
        if clients:
            for v in self.cfg.venues:
                paper = PaperExchange(v, lambda s, t, n=v.name: self.book.get(n, s), self.clock,
                                      sleep_until=simclock_sleep_until(self.clock),
                                      fill_ratio=(fill_ratio or {}).get(v.name, 1.0))
                self.spies[v.name] = Spy(paper, self.sent, gate, (expire or {}).get(v.name))
        self.portfolio = portfolio_from_config(self.cfg)
        self.bot = Bot(self.cfg, clients=self.spies or None, clock=self.clock, journal=self.journal,
                       portfolio=self.portfolio, inline_execution=inline, book=self.book, alerter=self.alerter)

    def requests(self) -> list[OrderRequest]:
        """Every order request, in the order it was sent."""
        return list(self.sent)

    def payloads(self, kind: str) -> list[Any]:
        return [p for k, _, p in self.journal.records if k == kind]


def open_long(w: World, *, venue: str = "A", qty: float = 0.5, target: float = 100.30, stop: float = 99.0,
              max_hold_s: float = 60.0) -> Position:
    pos = Position("pos-t", "sig-t", venue, BTC, Side.BUY, qty, 100.0, stop, target, w.clock.now(), max_hold_s)
    assert w.bot.monitor is not None
    w.bot.monitor.open(pos)
    return pos


# --------------------------------------------------------------------------- event order


async def test_quote_flows_book_risk_monitor_scanner_check_execute_in_order() -> None:
    w = World()
    bot = w.bot
    calls: list[str] = []

    def spy(obj: Any, name: str, label: str, check: Callable[..., None] | None = None) -> None:
        orig = getattr(obj, name)
        if asyncio.iscoroutinefunction(orig):
            async def wrapped(*a: Any, **k: Any) -> Any:
                calls.append(label)
                return await orig(*a, **k)
        else:
            def wrapped(*a: Any, **k: Any) -> Any:
                calls.append(label)
                if check is not None:
                    check(*a)
                return orig(*a, **k)
        setattr(obj, name, wrapped)

    def book_has_it(quote: Quote) -> None:
        assert w.book.get(quote.venue, quote.symbol) is quote  # the book is updated before the risk gate

    spy(w.book, "update", "book")
    spy(bot.risk, "on_quote", "risk.on_quote", book_has_it)
    spy(bot.monitor, "on_quote", "monitor")
    spy(bot.scanner, "on_quote", "scanner")
    spy(bot.risk, "check", "risk.check")
    spy(bot.engine, "execute", "execute")
    spy(bot.risk, "on_execution", "risk.on_execution")

    await bot.handle_event(q("A", 99.99, 100.00))
    assert calls == ["book", "risk.on_quote", "monitor", "scanner"]
    calls.clear()
    await bot.handle_event(q("B", 100.40, 100.41, T0 + 0.1))
    assert calls == ["book", "risk.on_quote", "monitor", "scanner", "risk.check", "execute", "risk.on_execution"]
    assert w.journal.kinds() == ["signal", "risk", "execution"]
    (sig_payload,), (decision,), (report,) = w.payloads("signal"), w.payloads("risk"), w.payloads("execution")
    sig = sig_payload["signal"]
    assert decision == {"signal_id": sig.id, "market": "BTC-USDT buy@A sell@B", "approved": True,
                        "size": 1.0, "reason": "ok", "scan_only": False}
    assert report.signal_id == sig.id and report.outcome is ExecutionOutcome.COMPLETED
    # BUY 1.0 @ 100.00 on A, SELL 1.0 @ 100.40 on B, fees 0.1 + 0.1004.
    assert report.realized_pnl == pytest.approx(0.40 - 0.2004, abs=1e-9)
    assert w.portfolio.balance("A", "BTC") == pytest.approx(2.0)
    assert w.portfolio.balance("B", "BTC") == pytest.approx(0.0)
    assert bot.counters.outcomes == {"completed": 1} and bot.counters.decisions == {"ok": 1}


async def test_exits_run_before_new_entries_and_entries_see_their_effect() -> None:
    """One B quote both hits a long position's target on B and opens an arb that sells on B.

    The exit (SELL 0.5 on B) goes first; the arb is then sized from B's remaining
    0.5 BTC, not the 1.0 it held before the exit.
    """
    w = World()
    open_long(w, venue="B", qty=0.5, target=100.30)
    await w.bot.handle_event(q("A", 99.99, 100.00))
    await w.bot.handle_event(q("B", 100.40, 100.41, T0 + 0.1))

    reqs = w.requests()
    assert [(r.venue, r.side, r.qty) for r in reqs] == [
        ("B", Side.SELL, 0.5),  # exit first
        ("A", Side.BUY, 0.5),  # then the arb, sized to B's remaining inventory
        ("B", Side.SELL, 0.5),
    ]
    assert w.journal.kinds() == ["execution", "signal", "risk", "execution"]
    exit_report = w.payloads("execution")[0]
    assert exit_report.outcome is ExecutionOutcome.CLOSED
    # 0.5 * (100.40 - 100.00) - exit fee 0.5 * 100.40 * 10 bps
    assert exit_report.realized_pnl == pytest.approx(0.2 - 0.0502, abs=1e-9)
    assert w.bot.monitor is not None and w.bot.monitor.positions == ()


async def test_out_of_order_and_invalid_quotes() -> None:
    w = World()
    bot = w.bot
    await bot.handle_event(q("A", 99.99, 100.00, seq=10))
    await bot.handle_event(q("A", 99.00, 99.01, T0 + 0.1, seq=9))  # older seq: dropped, nothing else runs
    assert w.book.get("A", BTC).seq == 10  # type: ignore[union-attr]
    assert bot.risk.tradable("A", BTC)
    await bot.handle_event(q("A", 100.10, 100.00, T0 + 0.2, seq=11))  # crossed: not stored, closes the gate
    assert w.book.get("A", BTC).seq == 10  # type: ignore[union-attr]
    assert not bot.risk.tradable("A", BTC)
    assert bot.counters.dropped_quotes == 2 and bot.counters.quotes == 3


# --------------------------------------------------------------------------- disconnects


async def test_disconnect_invalidates_the_venue_until_it_reconnects() -> None:
    w = World()
    bot = w.bot
    await bot.handle_event(q("A", 99.99, 100.00))
    await bot.handle_event(q("B", 99.99, 100.00))
    await bot.handle_event(FeedStatus("B", False, T0, "stall"))
    assert w.book.get("B", BTC) is None
    assert not bot.risk.tradable("B", BTC)

    # A moves 40 bps above B's last price: B's quotes are gone, so there is nothing to pair with.
    await bot.handle_event(q("A", 100.40, 100.41, T0 + 0.1))
    assert w.payloads("signal") == [] and w.requests() == []

    await bot.handle_event(FeedStatus("B", True, T0 + 0.2))
    assert bot.risk.tradable("B", BTC)
    await bot.handle_event(q("B", 99.99, 100.00, T0 + 0.3))
    (sig,) = [p["signal"] for p in w.payloads("signal")]
    assert sig.market == "BTC-USDT buy@B sell@A"
    assert [d["reason"] for d in w.payloads("risk")] == ["ok"]
    assert [p.connected for p in w.payloads("feed")] == [False, True]


async def test_sequence_reset_resync_lets_the_new_sequence_in() -> None:
    """The feed's seq_reset/resync status pair must clear the book, or the new low seqs would be dropped."""
    w = World()
    bot = w.bot
    await bot.handle_event(q("B", 99.99, 100.00, seq=500))
    await bot.handle_event(FeedStatus("B", False, T0 + 0.1, "seq_reset BTC-USDT 500->1"))
    await bot.handle_event(FeedStatus("B", True, T0 + 0.1, "resync"))
    await bot.handle_event(q("B", 99.98, 99.99, T0 + 0.1, seq=1))
    assert w.book.get("B", BTC).seq == 1  # type: ignore[union-attr]


# --------------------------------------------------------------------------- scan only


async def test_scan_only_logs_signals_and_decisions_but_never_executes() -> None:
    w = World(clients=False)
    bot = w.bot
    assert bot.scan_only and bot.engine is None and bot.monitor is None
    before = w.portfolio.snapshot()
    await bot.handle_event(q("A", 99.99, 100.00))
    await bot.handle_event(q("B", 100.40, 100.41, T0 + 0.1))
    await bot.handle_event(q("B", 100.45, 100.46, T0 + 0.2))
    await bot.tick()
    assert w.journal.kinds() == ["signal", "risk", "signal", "risk"]
    decisions = w.payloads("risk")
    assert all(d["approved"] and d["reason"] == "ok" and d["scan_only"] for d in decisions)
    assert bot.counters.approved == 2 and bot.counters.executions == 0 and bot.counters.outcomes == {}
    assert w.portfolio.snapshot() == before


def test_clients_must_cover_every_venue() -> None:
    cfg = make_cfg()
    clock = SimClock(T0)
    paper = PaperExchange(cfg.venue("A"), lambda s, t: None, clock, sleep_until=simclock_sleep_until(clock))
    with pytest.raises(ValueError, match=r"\['B'\]"):
        Bot(cfg, clients={"A": paper}, clock=clock, journal=None, portfolio=portfolio_from_config(cfg),
            inline_execution=True)


# --------------------------------------------------------------------------- in-flight limit


async def settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


async def test_at_most_one_execution_in_flight_per_symbol() -> None:
    gate = asyncio.Event()
    w = World(inline=False, gate=gate)
    bot = w.bot
    await bot.handle_event(q("A", 99.99, 100.00))
    await bot.handle_event(q("B", 100.40, 100.41, T0 + 0.1))
    await settle()
    assert bot.in_flight == (BTC,)
    assert len(w.requests()) == 2  # both legs, held at the gate

    # Still dislocated, but BTC is executing: journaled with reason in_flight, nothing sent.
    await bot.handle_event(q("B", 100.45, 100.46, T0 + 0.2))
    await settle()
    assert len(w.requests()) == 2
    assert [d["reason"] for d in w.payloads("risk")] == ["ok", IN_FLIGHT]

    # Another symbol is not blocked.
    await bot.handle_event(q("A", 99.99, 100.00, symbol=ETH))
    await bot.handle_event(q("B", 100.40, 100.41, T0 + 0.3, symbol=ETH))
    await settle()
    assert set(bot.in_flight) == {BTC, ETH}
    assert len(w.requests()) == 4

    gate.set()
    for _ in range(100):
        if not bot.in_flight:
            break
        await asyncio.sleep(0)
    assert bot.in_flight == ()
    assert bot.counters.outcomes == {"completed": 2}

    # Once done, BTC trades again (the other way: B sold its 1 BTC, A now holds 2).
    await bot.handle_event(q("B", 99.50, 99.51, T0 + 0.4))
    await settle()
    assert [d["reason"] for d in w.payloads("risk")] == ["ok", IN_FLIGHT, "ok", "ok"]
    assert len(w.requests()) == 6
    gate.set()
    for _ in range(100):
        if not bot.in_flight:
            break
        await asyncio.sleep(0)
    assert bot.counters.outcomes == {"completed": 3}


# --------------------------------------------------------------------------- halts


async def test_halted_bot_stops_entering_but_monitor_exits_still_run() -> None:
    w = World()
    bot = w.bot
    open_long(w, venue="A", qty=0.5, target=100.30)
    await bot.handle_event(q("A", 99.99, 100.00))
    bot.trip("operator")
    bot.trip("again")  # first cause kept, journaled and alerted once
    assert w.payloads("halt") == [{"reason": "operator", "context": "trip(operator)"}]
    assert len(w.alerter.texts) == 1 and "kill switch tripped: operator" in w.alerter.texts[0]

    # A dislocation: the signal is logged and rejected, nothing is sent.
    await bot.handle_event(q("B", 100.40, 100.41, T0 + 0.1))
    assert [d["reason"] for d in w.payloads("risk")] == ["halted:operator"]
    assert w.requests() == []

    # A's bid reaches the position's target: the exit still runs.
    await bot.handle_event(q("A", 100.35, 100.36, T0 + 0.2))
    (exit_req,) = w.requests()
    assert (exit_req.venue, exit_req.side, exit_req.qty) == ("A", Side.SELL, 0.5)
    assert w.payloads("execution")[-1].outcome is ExecutionOutcome.CLOSED
    assert bot.monitor is not None and bot.monitor.positions == ()
    assert len(w.payloads("halt")) == 1


async def test_residual_alerts_and_trips_the_kill_switch_once() -> None:
    # B never fills (sell leg and hedge expire); A fills BUYs but not SELLs (the unwind expires).
    w = World(fill_ratio={"B": 0.0}, expire={"A": Side.SELL})
    bot = w.bot
    await bot.handle_event(q("A", 99.99, 100.00))
    await bot.handle_event(q("B", 100.40, 100.41, T0 + 0.1))
    (report,) = w.payloads("execution")
    assert report.outcome is ExecutionOutcome.RESIDUAL and report.residual_qty == pytest.approx(1.0)
    assert [(r.venue, r.side) for r in w.requests()] == [
        ("A", Side.BUY), ("B", Side.SELL), ("B", Side.SELL), ("A", Side.SELL),  # legs, hedge, unwind
    ]
    assert bot.risk.halt_reason == "residual"
    assert w.payloads("halt") == [{"reason": "residual", "context": f"residual report for {report.signal_id}"}]
    assert len(w.alerter.texts) == 2
    assert w.alerter.texts[0].startswith("arbbot [paper] RESIDUAL on signal ")
    assert "kill switch tripped: residual" in w.alerter.texts[1]

    await bot.handle_event(q("B", 100.45, 100.46, T0 + 0.2))
    assert [d["reason"] for d in w.payloads("risk")] == ["ok", "halted:residual"]
    assert len(w.requests()) == 4 and len(w.payloads("halt")) == 1


async def test_engine_exception_is_reported_unknown_and_halts() -> None:
    w = World()
    bot = w.bot

    async def boom(*_: Any) -> Any:
        raise RuntimeError("bug")

    bot.engine.execute = boom  # type: ignore[method-assign,union-attr]
    await bot.handle_event(q("A", 99.99, 100.00))
    await bot.handle_event(q("B", 100.40, 100.41, T0 + 0.1))
    (report,) = w.payloads("execution")
    assert report.outcome is ExecutionOutcome.UNKNOWN
    assert "RuntimeError: bug" in report.notes[0]
    assert bot.risk.halt_reason == "unknown" and bot.counters.errors == 1
    assert any("UNKNOWN" in t for t in w.alerter.texts)


# --------------------------------------------------------------------------- live loop


class FakeFeed:
    def __init__(self, venue: str, events: list[FeedEvent]) -> None:
        self.venue = venue
        self.events = events
        self._stop = asyncio.Event()
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True
        self._stop.set()

    async def stream(self) -> AsyncIterator[FeedEvent]:
        yield FeedStatus(self.venue, True, T0)
        for ev in self.events:
            await asyncio.sleep(0)
            yield ev
        await self._stop.wait()
        yield FeedStatus(self.venue, False, T0, "stopped")


async def wait_for(cond: Callable[[], bool], timeout_s: float = 2.0) -> None:
    async with asyncio.timeout(timeout_s):
        while not cond():
            await asyncio.sleep(0.005)


async def test_run_consumes_feeds_drives_time_stops_and_shuts_down(tmp_path: Path) -> None:
    w = World(inline=False)
    bot = w.bot
    bot.tick_interval_s = 0.01
    open_long(w, venue="A", qty=0.5, target=200.0, max_hold_s=5.0)
    feeds = [FakeFeed("A", [q("A", 99.99, 100.00)]), FakeFeed("B", [q("B", 100.40, 100.41, T0 + 0.1)])]
    stop = asyncio.Event()
    runner = asyncio.create_task(bot.run(feeds, stop))

    await wait_for(lambda: bot.counters.outcomes.get("completed") == 1)  # the arb ran as a task
    assert bot.monitor is not None and len(bot.monitor.positions) == 1
    w.clock.set(T0 + 5.0)  # the position's time stop is due: only the periodic tick can see it
    await wait_for(lambda: bot.counters.outcomes.get("closed") == 1)
    closing = w.payloads("execution")[-1]
    assert closing.position_id == "pos-t" and "closed (time)" in closing.notes[0]

    stop.set()
    await asyncio.wait_for(runner, 5.0)
    assert all(f.stopped for f in feeds)
    kinds = w.journal.kinds()
    assert kinds[0] == "start" and kinds[-1] == "shutdown"
    shutdown = w.payloads("shutdown")[0]
    assert shutdown["positions"] == {"open": [], "residual": [], "unresolved": []}
    assert shutdown["outcomes"] == {"completed": 1, "closed": 1}
    assert w.book.get("A", BTC) is None and w.book.get("B", BTC) is None  # "stopped" invalidated both


async def test_run_survives_an_error_handling_an_event_but_stops_entering() -> None:
    w = World(inline=False)
    bot = w.bot
    orig = bot.scanner.on_quote
    state = {"n": 0}

    def flaky(*a: Any) -> Any:
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("scanner bug")
        return orig(*a)

    bot.scanner.on_quote = flaky  # type: ignore[method-assign]
    feeds = [FakeFeed("A", [q("A", 99.99, 100.00)]), FakeFeed("B", [q("B", 100.40, 100.41, T0 + 0.1)])]
    stop = asyncio.Event()
    runner = asyncio.create_task(bot.run(feeds, stop))
    await wait_for(lambda: bot.counters.signals == 1)
    stop.set()
    await asyncio.wait_for(runner, 5.0)
    assert bot.counters.errors == 1
    assert bot.risk.halt_reason == "internal_error"
    assert [d["reason"] for d in w.payloads("risk")] == ["halted:internal_error"]
    assert w.requests() == []


async def test_run_reports_positions_left_open(tmp_path: Path) -> None:
    w = World(inline=False)
    open_long(w, venue="A", qty=0.5, target=200.0, max_hold_s=3600.0)
    stop = asyncio.Event()
    stop.set()
    await w.bot.run([FakeFeed("A", [])], stop)
    assert w.payloads("shutdown")[0]["positions"]["open"] == ["pos-t"]
    assert any("positions not flat" in t and "pos-t" in t for t in w.alerter.texts)


async def test_journal_file_has_signal_risk_execution_records(tmp_path: Path) -> None:
    cfg = make_cfg()
    clock = SimClock(T0)
    book = QuoteBook()
    path = tmp_path / "journal.jsonl"
    journal = Journal(path)
    clients = {v.name: PaperExchange(v, lambda s, t, n=v.name: book.get(n, s), clock,
                                     sleep_until=simclock_sleep_until(clock)) for v in cfg.venues}
    bot = Bot(cfg, clients=clients, clock=clock, journal=journal, portfolio=portfolio_from_config(cfg),
              inline_execution=True, book=book)
    await bot.handle_event(q("A", 99.99, 100.00))
    await bot.handle_event(q("B", 100.40, 100.41, T0 + 0.1))
    journal.close()
    recs = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["kind"] for r in recs] == ["signal", "risk", "execution"]
    sig = recs[0]["signal"]
    assert sig["kind"] == "cross_venue" and sig["market"] == "BTC-USDT buy@A sell@B"
    assert sig["gross_edge_bps"] == pytest.approx(40.0) and sig["net_edge_bps"] == pytest.approx(20.0)
    assert recs[1]["signal_id"] == sig["id"] == recs[2]["signal_id"]
    assert recs[2]["outcome"] == "completed" and len(recs[2]["orders"]) == 2


# --------------------------------------------------------------------------- review findings (regressions)


def lag_world_cfg(*, btc: float = 1.0, min_net_edge_bps: float = 100.0) -> BotConfig:
    """A is the reference and B the target (both BTC-USDT); 10 bps fees, warm after one sample."""
    from dataclasses import replace

    from arbbot.config import ReferenceLagConfig

    base = make_cfg()
    venues = tuple(replace(v, starting_balances={"USDT": 10_000.0, "BTC": btc}) for v in base.venues)
    return replace(
        base, venues=venues,
        signal=SignalConfig(min_net_edge_bps=min_net_edge_bps, participation=0.5, cooldown_ms=0.0),
        reference_lag=ReferenceLagConfig(enabled=True, reference_venue="A", reference_symbol=BTC, target_venue="B",
                                         target_symbol=BTC, min_basis_samples=1, entry_threshold_bps=5.0,
                                         stop_bps=15.0, max_hold_s=30.0),
    )


class FailingJournal(CaptureJournal):
    """The disk fills up: every write of one of ``kinds`` (all kinds if empty) raises OSError."""

    def __init__(self, *kinds: str) -> None:
        super().__init__()
        self.fail = set(kinds)

    def record(self, kind: str, ts: float, payload: Any) -> None:
        if not self.fail or kind in self.fail:
            raise OSError(27, "File too large")
        super().record(kind, ts, payload)


async def test_journal_failure_during_a_live_entry_leaves_the_position_monitored_and_halts() -> None:
    w = World(inline=False, cfg=lag_world_cfg())
    w.bot.journal = w.journal = FailingJournal("execution")
    bot = w.bot
    await bot.handle_event(q("A", 100.00, 100.01))
    await bot.handle_event(q("B", 100.50, 100.51))  # basis sample: +50 bps
    await bot.handle_event(q("B", 100.00, 100.01, T0 + 0.1))  # B lags fair 100.505: BUY 2.5 on B
    task = bot._inflight[BTC]
    await settle()
    assert task.done() and task.exception() is None  # nothing escapes the execution task
    assert bot.monitor is not None
    (pos,) = bot.monitor.positions  # handed to the monitor: it has a stop
    assert (pos.venue, pos.side, pos.qty) == ("B", Side.BUY, 2.5)
    assert bot.risk.halt_reason == "journal_error"
    assert any("journal write failed" in t for t in w.alerter.texts)
    assert any("kill switch tripped: journal_error" in t for t in w.alerter.texts)

    await bot.handle_event(q("B", 98.00, 98.01, T0 + 0.2))  # through the stop: the exit still runs
    assert [(r.venue, r.side, r.qty) for r in w.requests()][-1] == ("B", Side.SELL, 2.5)
    assert bot.monitor.positions == ()


async def test_alerts_go_out_even_when_the_journal_cannot_be_written() -> None:
    w = World()
    w.bot.journal = FailingJournal()  # every write fails
    w.bot.trip("operator")  # must not raise
    assert any("kill switch tripped: operator" in t for t in w.alerter.texts)
    assert w.bot.counters.errors >= 1


async def test_an_execution_task_that_raises_trips_the_kill_switch_and_alerts() -> None:
    w = World(inline=False)
    bot = w.bot

    def broken(report: Any) -> None:
        raise RuntimeError("bug in reporting")

    bot.risk.on_execution = broken  # type: ignore[method-assign]
    await bot.handle_event(q("A", 99.99, 100.00))
    await bot.handle_event(q("B", 100.40, 100.41, T0 + 0.1))
    await settle()
    assert bot.in_flight == ()
    assert bot.risk.halt_reason == "internal_error" and bot.counters.errors == 1
    assert any("execution execute-" in t and "RuntimeError" in t for t in w.alerter.texts)


async def test_an_arb_never_sells_the_inventory_an_open_position_needs_for_its_exit() -> None:
    w = World(cfg=lag_world_cfg(btc=0.0, min_net_edge_bps=5.0))
    bot = w.bot
    balances: list[float] = []

    async def step(quote: Quote) -> None:
        await bot.handle_event(quote)
        balances.append(w.portfolio.balance("B", BTC))

    await step(q("A", 100.00, 100.01))
    await step(q("B", 100.10, 100.11))  # basis sample: +10 bps
    await step(q("B", 99.70, 99.71, T0 + 0.1))  # B lags: reference-lag BUY 2.5 on B
    assert bot.monitor is not None and [p.qty for p in bot.monitor.positions] == [2.5]
    await step(q("A", 99.40, 99.41, T0 + 0.2))  # buy A / sell B would pay, but B's coins back the position
    assert [(r.venue, r.side) for r in w.requests()] == [("B", Side.BUY)]
    await step(q("B", 99.40, 99.41, T0 + 0.3))  # through the stop: the exit sells what B holds
    assert [(r.venue, r.side, r.qty) for r in w.requests()][-1] == ("B", Side.SELL, 2.5)
    assert bot.monitor.positions == () and min(balances) >= 0.0  # never short on spot
