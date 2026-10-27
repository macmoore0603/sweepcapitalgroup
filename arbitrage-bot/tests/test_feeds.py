"""Venue adapters (against real captured frames) and the reconnecting WebSocketFeed (no network)."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from arbbot.clock import SimClock, WallClock
from arbbot.config import InstrumentConfig, VenueConfig
from arbbot.feeds.base import QuoteBook
from arbbot.feeds.venues import (
    ADAPTERS,
    BinanceAdapter,
    BybitAdapter,
    CoinbaseAdapter,
    KrakenAdapter,
    OkxAdapter,
    new_adapter,
    parse_rfc3339,
)
from arbbot.feeds.ws import DEFAULT_CONNECT_KWARGS, WebSocketFeed, merge_feeds
from arbbot.models import FeedEvent, FeedStatus, Quote

FIXTURES = Path(__file__).parent / "fixtures"

SYMBOLS = {
    "binance": {"BTCUSDT": "BTC-USDT"},
    "bybit": {"BTCUSDT": "BTC-USDT"},
    "kraken": {"BTC/USD": "BTC-USD"},
    "coinbase": {"BTC-USD": "BTC-USD"},
    "okx": {"BTC-USDT": "BTC-USDT"},
}


def frame(venue: str) -> str:
    return (FIXTURES / f"{venue}_frame.json").read_text(encoding="utf-8").strip()


def fixture_lines(name: str) -> list[str]:
    path = FIXTURES / name
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()] if path.exists() else []


def utc(*args: int) -> float:
    return datetime(*args, tzinfo=timezone.utc).timestamp()


def inst(symbol: str, venue_symbol: str) -> InstrumentConfig:
    return InstrumentConfig(symbol=symbol, venue_symbol=venue_symbol)


def venue_cfg(name: str, feed: str, *instruments: InstrumentConfig) -> VenueConfig:
    return VenueConfig(name=name, feed=feed, taker_fee_bps=10.0, instruments=instruments)


# OKX resets connections from the build sandbox, so its frames are the official
# docs examples (https://www.okx.com/docs-v5/en/, "WS / Order book channel").
OKX_BBO_DOC = (
    '{"arg":{"channel":"bbo-tbt","instId":"BCH-USDT-SWAP"},"data":[{"asks":[["111.06","55154","0","2"]],'
    '"bids":[["111.05","57745","0","2"]],"ts":"1670324386802","seqId":363996337}]}'
)
OKX_SUB_ACK_DOC = '{"id":"1512","event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT"},"connId":"a4d3ae55"}'
OKX_NOTICE_DOC = (
    '{"event":"notice","code":"64008","msg":"The connection will soon be closed for a service upgrade. '
    'Please reconnect.","connId":"a4d3ae55"}'
)
OKX_CONN_COUNT_DOC = '{"event":"channel-conn-count","channel":"orders","connCount":"2","connId":"abcd1234"}'
OKX_ERROR_DOC = (
    '{"id":"1512","event":"error","code":"60012","msg":"Invalid request: {\\"op\\": \\"subscribe\\", '
    '\\"argss\\":[{ \\"channel\\" : \\"books\\", \\"instId\\" : \\"BTC-USD-191227\\"}]}","connId":"a4d3ae55"}'
)
OKX_CONN_COUNT_ERROR_DOC = (
    '{"event":"channel-conn-count-error","channel":"orders","connCount":"30","connId":"a4d3ae55"}'
)
# Binance docs examples (binance-spot-api-docs, web-socket-streams.md).
BINANCE_SHUTDOWN_DOC = '{"stream":"!serverShutdown","data":{"e":"serverShutdown","E":1770123456789}}'
BINANCE_ERROR_DOC = '{"code": 2, "msg": "Invalid request: request ID must be an unsigned integer"}'


# ---------------------------------------------------------------------------
# adapters: real frames


def test_binance_parses_captured_combined_stream_frame() -> None:
    quotes = ADAPTERS["binance"].parse(frame("binance"), 1000.0, SYMBOLS["binance"])
    assert quotes == [
        Quote(venue="binance", symbol="BTC-USDT", bid=79614.0, bid_size=6.10691, ask=79614.01,
              ask_size=1.66135, ts_local=1000.0, ts_exchange=None, seq=101958358644)
    ]


def test_binance_parses_raw_stream_payload_and_bytes() -> None:
    payload = json.dumps(json.loads(frame("binance"))["data"])
    a = BinanceAdapter()
    assert a.parse(payload, 5.0, SYMBOLS["binance"]) == a.parse(frame("binance").encode(), 5.0, SYMBOLS["binance"])
    assert a.parse(payload, 5.0, SYMBOLS["binance"])[0].bid == 79614.0


def test_bybit_parses_captured_level1_snapshot() -> None:
    quotes = BybitAdapter().parse(frame("bybit"), 1000.0, SYMBOLS["bybit"])
    assert quotes == [
        Quote(venue="bybit", symbol="BTC-USDT", bid=79620.7, bid_size=0.320203, ask=79620.8,
              ask_size=1.303179, ts_local=1000.0, ts_exchange=1793096565.852, seq=133209405)
    ]


def test_kraken_parses_captured_ticker_snapshot() -> None:
    quotes = ADAPTERS["kraken"].parse(frame("kraken"), 1000.0, SYMBOLS["kraken"])
    assert quotes == [
        Quote(venue="kraken", symbol="BTC-USD", bid=79487.5, bid_size=0.27320408, ask=79487.6,
              ask_size=0.44882569, ts_local=1000.0, ts_exchange=utc(2026, 10, 27, 10, 22, 50) + 0.153298, seq=None)
    ]


def test_coinbase_parses_captured_ticker() -> None:
    quotes = ADAPTERS["coinbase"].parse(frame("coinbase"), 1000.0, SYMBOLS["coinbase"])
    assert quotes == [
        Quote(venue="coinbase", symbol="BTC-USD", bid=79473.85, bid_size=0.04208915, ask=79473.86,
              ask_size=0.22768983, ts_local=1000.0, ts_exchange=utc(2026, 10, 27, 10, 22, 58) + 0.479146178, seq=0)
    ]


def test_okx_parses_docs_bbo_tbt_example() -> None:
    quotes = OkxAdapter().parse(OKX_BBO_DOC, 1000.0, {"BCH-USDT-SWAP": "BCH-USDT"})
    assert quotes == [
        Quote(venue="okx", symbol="BCH-USDT", bid=111.05, bid_size=57745.0, ask=111.06, ask_size=55154.0,
              ts_local=1000.0, ts_exchange=1670324386.802, seq=363996337)
    ]


def test_okx_keepalive_push_with_empty_book_yields_nothing() -> None:
    raw = '{"arg":{"channel":"bbo-tbt","instId":"BTC-USDT"},"data":[{"asks":[],"bids":[],"ts":"1","seqId":5}]}'
    assert OkxAdapter().parse(raw, 1.0, SYMBOLS["okx"]) == []


CONTROL_FRAMES = [
    (venue, line)
    for venue in ("binance", "bybit", "kraken", "coinbase")
    for line in fixture_lines(f"{venue}_control.jsonl")
] + [
    ("binance", BINANCE_SHUTDOWN_DOC),
    ("okx", "pong"),
    ("okx", OKX_SUB_ACK_DOC),
    ("okx", OKX_NOTICE_DOC),
    ("okx", OKX_CONN_COUNT_DOC),
]


def test_control_fixtures_present() -> None:
    venues = {v for v, _ in CONTROL_FRAMES}
    assert venues == {"binance", "bybit", "kraken", "coinbase", "okx"}
    assert len(CONTROL_FRAMES) >= 13


@pytest.mark.parametrize(("venue", "raw"), CONTROL_FRAMES)
def test_control_frames_return_no_quotes(venue: str, raw: str) -> None:
    assert new_adapter(venue).parse(raw, 1.0, SYMBOLS[venue]) == []


ERROR_FRAMES = [
    (venue, line) for venue in ("bybit", "kraken", "coinbase") for line in fixture_lines(f"{venue}_errors.jsonl")
] + [
    ("binance", BINANCE_ERROR_DOC),
    ("okx", OKX_ERROR_DOC),
    ("okx", OKX_CONN_COUNT_ERROR_DOC),
]


@pytest.mark.parametrize(("venue", "raw"), ERROR_FRAMES)
def test_venue_error_frames_raise(venue: str, raw: str) -> None:
    with pytest.raises(ValueError):
        new_adapter(venue).parse(raw, 1.0, SYMBOLS[venue])


def _binance_with(**changes: Any) -> str:
    d = json.loads(frame("binance"))
    d["data"].update(changes)
    return json.dumps(d)


def _without(venue: str, path: tuple[Any, ...]) -> str:
    d = json.loads(frame(venue))
    node = d
    for k in path[:-1]:
        node = node[k]
    del node[path[-1]]
    return json.dumps(d)


MALFORMED = [
    ("binance", "not json"),
    ("binance", "[1, 2, 3]"),
    ("binance", b"\xff\xfe\x00"),
    ("binance", _without("binance", ("data", "a"))),
    ("binance", _binance_with(b="abc")),
    ("binance", _binance_with(B="NaN")),
    ("binance", _binance_with(a=None)),
    ("binance", _binance_with(u="x1")),
    ("binance", '{"hello": "world"}'),
    ("bybit", frame("bybit").replace('"snapshot"', '"partial"')),
    ("bybit", _without("bybit", ("data", "s"))),
    ("bybit", _without("bybit", ("data", "u"))),
    ("bybit", frame("bybit").replace('["79620.7","0.320203"]', '["79620.7"]')),
    ("bybit", frame("bybit").replace('"orderbook.1.BTCUSDT"', '"tickers.BTCUSDT"')),
    ("bybit", '{"retCode": 0}'),
    ("kraken", _without("kraken", ("data", 0, "ask_qty"))),
    ("kraken", frame("kraken").replace("2026-10-27T10:22:50.153298Z", "yesterday")),
    ("kraken", frame("kraken").replace('"type":"snapshot"', '"type":"bogus"')),
    ("kraken", '{"channel":"ticker","type":"update","data":{"symbol":"BTC/USD"}}'),
    ("kraken", '{"unexpected": true}'),
    ("coinbase", _without("coinbase", ("events", 0, "tickers", 0, "best_ask"))),
    ("coinbase", frame("coinbase").replace('"best_bid":"79473.85"', '"best_bid":""')),
    ("coinbase", '{"channel":"level2","events":[]}'),
    ("okx", '{"data":[]}'),
    ("okx", OKX_BBO_DOC.replace('"111.05"', '"oops"')),
    ("okx", OKX_BBO_DOC.replace('"bbo-tbt"', '"trades"')),
    ("okx", OKX_BBO_DOC.replace('["111.06","55154","0","2"]', '["111.06"]')),
    ("okx", "ping?"),
]


@pytest.mark.parametrize(("venue", "raw"), MALFORMED)
def test_malformed_frames_raise_value_error(venue: str, raw: str | bytes) -> None:
    symbols = {"BCH-USDT-SWAP": "BCH-USDT", **SYMBOLS[venue]}
    with pytest.raises(ValueError):
        new_adapter(venue).parse(raw, 1.0, symbols)


def test_unknown_symbols_are_skipped_and_lookup_ignores_case() -> None:
    a = BinanceAdapter()
    assert a.parse(frame("binance"), 1.0, {"ETHUSDT": "ETH-USDT"}) == []
    assert a.parse(frame("binance"), 1.0, {"btcusdt": "BTC-USDT"})[0].symbol == "BTC-USDT"
    assert BybitAdapter().parse(frame("bybit"), 1.0, {}) == []
    assert KrakenAdapter().parse(frame("kraken"), 1.0, {"ETH/USD": "ETH-USD"}) == []
    assert CoinbaseAdapter().parse(frame("coinbase"), 1.0, {}) == []
    assert OkxAdapter().parse(OKX_BBO_DOC, 1.0, {}) == []


def _bybit(kind: str, u: int, b: list[list[str]], a: list[list[str]], sym: str = "BTCUSDT") -> str:
    return json.dumps({"topic": f"orderbook.1.{sym}", "ts": 1000, "type": kind,
                       "data": {"s": sym, "b": b, "a": a, "u": u, "seq": 7}, "cts": 999})


def _top(q: Quote) -> tuple[float, float, float, float, int | None]:
    return (q.bid, q.bid_size, q.ask, q.ask_size, q.seq)


def test_bybit_level1_deltas_keep_last_known_side() -> None:
    a, s = BybitAdapter(), SYMBOLS["bybit"]
    [q] = a.parse(_bybit("snapshot", 1, [["100", "1"]], [["101", "2"]]), 1.0, s)
    assert _top(q) == (100.0, 1.0, 101.0, 2.0, 1)
    assert q.ts_exchange == 0.999  # cts (matching engine) preferred over ts
    # delta omits the ask side: keep the last ask
    [q] = a.parse(_bybit("delta", 2, [["100.5", "3"]], []), 1.0, s)
    assert _top(q) == (100.5, 3.0, 101.0, 2.0, 2)
    # deleting a price that is not the top changes nothing
    [q] = a.parse(_bybit("delta", 3, [], [["105", "0"]]), 1.0, s)
    assert _top(q) == (100.5, 3.0, 101.0, 2.0, 3)
    # deleting the top ask with no replacement: one-sided book, no quote
    assert a.parse(_bybit("delta", 4, [], [["101", "0"]]), 1.0, s) == []
    assert a.parse(_bybit("delta", 5, [["100.6", "1"]], []), 1.0, s) == []
    # a new ask level restores the quote (with the newest bid)
    [q] = a.parse(_bybit("delta", 6, [], [["101", "0"], ["101.2", "4"]]), 1.0, s)
    assert _top(q) == (100.6, 1.0, 101.2, 4.0, 6)
    # a snapshot is the full state: an empty side really is empty
    assert a.parse(_bybit("snapshot", 7, [], [["101.1", "1"]]), 1.0, s) == []
    assert a.parse(_bybit("delta", 8, [], [["101.0", "1"]]), 1.0, s) == []
    [q] = a.parse(_bybit("delta", 9, [["100.9", "2"]], []), 1.0, s)
    assert _top(q) == (100.9, 2.0, 101.0, 1.0, 9)


def test_bybit_reset_forgets_book_state_and_symbols_are_independent() -> None:
    a, s = BybitAdapter(), {"BTCUSDT": "BTC-USDT", "ETHUSDT": "ETH-USDT"}
    a.parse(_bybit("snapshot", 1, [["100", "1"]], [["101", "2"]]), 1.0, s)
    assert a.parse(_bybit("delta", 1, [["50", "1"]], [], sym="ETHUSDT"), 1.0, s) == []
    [q] = a.parse(_bybit("delta", 2, [["100.5", "1"]], []), 1.0, s)
    assert q.symbol == "BTC-USDT" and q.ask == 101.0
    a.reset()
    assert a.parse(_bybit("delta", 3, [["100.7", "1"]], []), 1.0, s) == []


def test_kraken_update_with_several_symbols() -> None:
    raw = json.dumps({"channel": "ticker", "type": "update", "data": [
        {"symbol": "BTC/USD", "bid": 1.5, "bid_qty": 2, "ask": 1.6, "ask_qty": 3, "timestamp": "2026-01-01T00:00:00Z"},
        {"symbol": "ETH/USD", "bid": 0.5, "bid_qty": 1, "ask": 0.6, "ask_qty": 4},
    ]})
    quotes = KrakenAdapter().parse(raw, 9.0, {"BTC/USD": "BTC-USD", "ETH/USD": "ETH-USD"})
    assert [(q.symbol, q.bid, q.bid_size, q.ask, q.ask_size, q.ts_exchange) for q in quotes] == [
        ("BTC-USD", 1.5, 2.0, 1.6, 3.0, utc(2026, 1, 1)),
        ("ETH-USD", 0.5, 1.0, 0.6, 4.0, None),
    ]


def test_coinbase_batched_tickers_keep_only_latest_per_product() -> None:
    def t(pid: str, bid: str) -> dict[str, str]:
        return {"type": "ticker", "product_id": pid, "best_bid": bid, "best_bid_quantity": "1",
                "best_ask": "200", "best_ask_quantity": "2"}

    raw = json.dumps({"channel": "ticker", "timestamp": "2026-10-27T10:00:00Z", "sequence_num": 42,
                      "events": [{"type": "update", "tickers": [t("BTC-USD", "100"), t("ETH-USD", "10")]},
                                 {"type": "update", "tickers": [t("BTC-USD", "101")]}]})
    quotes = CoinbaseAdapter().parse(raw, 1.0, {"BTC-USD": "BTC-USD", "ETH-USD": "ETH-USD"})
    assert [(q.symbol, q.bid, q.seq) for q in quotes] == [("ETH-USD", 10.0, 42), ("BTC-USD", 101.0, 42)]


# ---------------------------------------------------------------------------
# adapters: endpoints, subscriptions, heartbeats


def test_adapter_registry() -> None:
    assert set(ADAPTERS) == {"binance", "bybit", "kraken", "coinbase", "okx"}
    for key, adapter in ADAPTERS.items():
        assert adapter.name == key
        fresh = new_adapter(key)
        assert type(fresh) is type(adapter) and fresh is not adapter
    with pytest.raises(KeyError):
        new_adapter("ftx")


def test_binance_url_subscribes_combined_streams() -> None:
    a = BinanceAdapter()
    insts = [inst("BTC-USDT", "BTCUSDT"), inst("ETH-USDT", "ETHUSDT")]
    assert a.url(insts) == "wss://data-stream.binance.vision/stream?streams=btcusdt@bookTicker/ethusdt@bookTicker"
    assert a.subscribe_messages(insts) == []
    assert a.heartbeat() is None  # protocol-level pings are answered by the websocket library
    with pytest.raises(ValueError):
        a.url([])


def test_bybit_subscribe_chunks_ten_args_and_pings() -> None:
    a = BybitAdapter()
    assert a.url([inst("BTC-USDT", "BTCUSDT")]) == "wss://stream.bybit.com/v5/public/spot"
    assert a.subscribe_messages([inst("BTC-USDT", "BTCUSDT")]) == ['{"op":"subscribe","args":["orderbook.1.BTCUSDT"]}']
    many = [inst(f"C{i}-USDT", f"C{i}USDT") for i in range(12)]
    msgs = [json.loads(m) for m in a.subscribe_messages(many)]
    assert [m["args"] for m in msgs] == [
        [f"orderbook.1.C{i}USDT" for i in range(10)],
        ["orderbook.1.C10USDT", "orderbook.1.C11USDT"],
    ]
    assert a.heartbeat() == (20.0, '{"op":"ping"}')


def test_kraken_coinbase_okx_subscriptions() -> None:
    k = KrakenAdapter()
    assert k.url([inst("BTC-USD", "BTC/USD")]) == "wss://ws.kraken.com/v2"
    assert k.subscribe_messages([inst("BTC-USD", "BTC/USD"), inst("ETH-USD", "ETH/USD")]) == [
        '{"method":"subscribe","params":{"channel":"ticker","symbol":["BTC/USD","ETH/USD"],'
        '"event_trigger":"bbo","snapshot":true}}'
    ]
    assert k.heartbeat() is None  # server sends {"channel":"heartbeat"} every second when idle

    c = CoinbaseAdapter()
    assert c.url([inst("BTC-USD", "BTC-USD")]) == "wss://advanced-trade-ws.coinbase.com"
    assert c.subscribe_messages([inst("BTC-USD", "BTC-USD")]) == [
        '{"type":"subscribe","product_ids":["BTC-USD"],"channel":"ticker"}',
        '{"type":"subscribe","channel":"heartbeats"}',
    ]
    assert c.heartbeat() is None  # the heartbeats subscription keeps the socket open

    o = OkxAdapter()
    assert o.url([inst("BTC-USDT", "BTC-USDT")]) == "wss://ws.okx.com/ws/v5/public"
    assert o.subscribe_messages([inst("BTC-USDT", "BTC-USDT")]) == [
        '{"op":"subscribe","args":[{"channel":"bbo-tbt","instId":"BTC-USDT"}]}'
    ]
    assert o.heartbeat() == (20.0, "ping")
    with pytest.raises(ValueError):
        OkxAdapter(ping_interval_s=30.0)


def test_parse_rfc3339_keeps_fraction_and_offset() -> None:
    assert parse_rfc3339("2026-10-27T10:22:58.47916167Z") == utc(2026, 10, 27, 10, 22, 58) + 0.47916167
    assert parse_rfc3339("2026-10-27T12:22:58+02:00") == utc(2026, 10, 27, 10, 22, 58)
    assert parse_rfc3339("2026-10-27T10:22:58Z") == utc(2026, 10, 27, 10, 22, 58)
    for bad in ("2026-10-27", "10:22:58Z", "2026-10-27T10:22:58", 12345):
        with pytest.raises(ValueError):
            parse_rfc3339(bad)


# ---------------------------------------------------------------------------
# WebSocketFeed with an injected fake connection

HANG = object()  # FakeWS item: block until the connection is closed


class FakeClosed(Exception):
    pass


class FakeWS:
    """Scripted connection. Items: str/bytes frame, Exception to raise, callable side
    effect, or HANG (deliver only replies from ``respond`` until closed). After the
    last item the 'server' closes the connection."""

    def __init__(self, *items: Any, respond: Callable[[str], str | None] | None = None) -> None:
        self.items = list(items)
        self.sent: list[str] = []
        self.closed = False
        self._closed_ev = asyncio.Event()
        self._respond = respond
        self._replies: asyncio.Queue[str] = asyncio.Queue()

    async def send(self, msg: str) -> None:
        if self.closed:
            raise FakeClosed("send on closed socket")
        self.sent.append(msg)
        reply = self._respond(msg) if self._respond is not None else None
        if reply is not None:
            self._replies.put_nowait(reply)

    async def recv(self) -> str | bytes:
        while True:
            if self.closed:
                raise FakeClosed("closed")
            if not self.items:
                raise FakeClosed("server closed")
            item = self.items.pop(0)
            if item is HANG:
                self.items.insert(0, HANG)
                reply = asyncio.ensure_future(self._replies.get())
                closed = asyncio.ensure_future(self._closed_ev.wait())
                try:
                    await asyncio.wait({reply, closed}, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    reply.cancel()
                    closed.cancel()
                if self.closed:
                    raise FakeClosed("closed")
                return reply.result()
            if isinstance(item, BaseException):
                raise item
            if callable(item):
                item()
                continue
            await asyncio.sleep(0)
            return item

    async def close(self) -> None:
        self.closed = True
        self._closed_ev.set()


class FakeConnect:
    def __init__(self, *script: Any) -> None:
        self.script = list(script)
        self.urls: list[str] = []
        self.kwargs: list[dict[str, Any]] = []

    async def __call__(self, url: str, **kwargs: Any) -> FakeWS:
        self.urls.append(url)
        self.kwargs.append(kwargs)
        await asyncio.sleep(0)
        if not self.script:
            raise ConnectionRefusedError("script exhausted")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class Sleeps:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        await asyncio.sleep(0)


async def collect(
    feed: WebSocketFeed, stop_when: Callable[[list[FeedEvent]], bool], limit: int = 200
) -> list[FeedEvent]:
    async def run() -> list[FeedEvent]:
        events: list[FeedEvent] = []
        async for ev in feed.stream():
            events.append(ev)
            if not feed.stopped and stop_when(events):
                feed.stop()
            assert len(events) < limit, "runaway stream"
        return events

    return await asyncio.wait_for(run(), timeout=5.0)


def n_quotes(n: int) -> Callable[[list[FeedEvent]], bool]:
    return lambda evs: sum(isinstance(e, Quote) for e in evs) >= n


def summary(events: list[FeedEvent]) -> list[tuple[Any, ...]]:
    out: list[tuple[Any, ...]] = []
    for e in events:
        if isinstance(e, FeedStatus):
            out.append(("status", e.connected, e.reason))
        else:
            out.append(("quote", e.symbol, e.seq))
    return out


def binance_frame(u: int, bid: str = "100.0") -> str:
    return json.dumps({"stream": "btcusdt@bookTicker",
                       "data": {"u": u, "s": "BTCUSDT", "b": bid, "B": "1", "a": "100.5", "A": "2"}})


BINANCE = venue_cfg("binance", "binance", inst("BTC-USDT", "BTCUSDT"))
BYBIT = venue_cfg("bybit_spot", "bybit", inst("BTC-USDT", "BTCUSDT"))
R0 = (0.8444218515250481, 0.7579544029403025, 0.420571580830845, 0.25891675029296335)  # random.Random(0)


def jit(base: float, r: float) -> float:
    return base * (0.5 + 0.5 * r)


async def test_feed_subscribes_reports_connected_and_yields_quotes() -> None:
    clock = SimClock(1000.0)
    ack = fixture_lines("bybit_control.jsonl")[0]
    ws = FakeWS(ack, lambda: clock.set(1000.5), frame("bybit"), HANG)
    conn = FakeConnect(ws)
    feed = WebSocketFeed(BybitAdapter(), BYBIT, clock, connect=conn, sleep=Sleeps())
    events = await collect(feed, n_quotes(1))

    assert conn.urls == ["wss://stream.bybit.com/v5/public/spot"]
    assert conn.kwargs == [dict(DEFAULT_CONNECT_KWARGS)]
    assert ws.sent[0] == '{"op":"subscribe","args":["orderbook.1.BTCUSDT"]}'
    assert events == [
        FeedStatus("bybit_spot", True, 1000.0),
        Quote(venue="bybit_spot", symbol="BTC-USDT", bid=79620.7, bid_size=0.320203, ask=79620.8,
              ask_size=1.303179, ts_local=1000.5, ts_exchange=1793096565.852, seq=133209405),
        FeedStatus("bybit_spot", False, 1000.5, "stopped"),
    ]
    assert ws.closed
    assert (feed.stats.connects, feed.stats.messages, feed.stats.quotes, feed.stats.disconnects) == (1, 2, 1, 0)


async def test_feed_reconnects_with_exponential_backoff_and_seeded_jitter() -> None:
    clock = SimClock(0.0)
    sleeps = Sleeps()
    ws1 = FakeWS(binance_frame(1))  # server closes after one frame
    ws2 = FakeWS(binance_frame(2), HANG)
    conn = FakeConnect(ws1, ConnectionRefusedError("refused"), OSError("unreachable"), ws2)
    feed = WebSocketFeed(BinanceAdapter(), BINANCE, clock, connect=conn, sleep=sleeps, seed=0)
    events = await collect(feed, n_quotes(2))

    assert summary(events) == [
        ("status", True, ""),
        ("quote", "BTC-USDT", 1),
        ("status", False, "disconnected: FakeClosed: server closed"),
        ("status", False, "connect failed: ConnectionRefusedError: refused"),
        ("status", False, "connect failed: OSError: unreachable"),
        ("status", True, ""),
        ("quote", "BTC-USDT", 2),
        ("status", False, "stopped"),
    ]
    # attempt n waits uniform[d/2, d] with d = 0.5 * 2**n, drawn from random.Random(seed)
    assert sleeps.delays == [jit(0.5, R0[0]), jit(1.0, R0[1]), jit(2.0, R0[2])]
    assert conn.urls == [BinanceAdapter().url(BINANCE.instruments)] * 4
    assert (feed.stats.connects, feed.stats.disconnects) == (2, 3)


async def test_backoff_resets_only_after_a_stable_connection() -> None:
    clock = SimClock(0.0)
    sleeps = Sleeps()
    stable = FakeWS(binance_frame(1), lambda: clock.advance(15.0))  # up 15 s, then dropped
    conn = FakeConnect(ConnectionRefusedError("a"), ConnectionRefusedError("b"), stable,
                       ConnectionRefusedError("c"), FakeWS(HANG))
    feed = WebSocketFeed(BinanceAdapter(), BINANCE, clock, connect=conn, sleep=sleeps, stable_after_s=10.0)
    await collect(feed, lambda evs: sum(isinstance(e, FeedStatus) and e.connected for e in evs) >= 2)
    assert sleeps.delays == [jit(0.5, R0[0]), jit(1.0, R0[1]), jit(0.5, R0[2]), jit(1.0, R0[3])]

    clock2 = SimClock(0.0)
    sleeps2 = Sleeps()
    unstable = FakeWS(binance_frame(1), lambda: clock2.advance(5.0))  # up only 5 s
    conn2 = FakeConnect(ConnectionRefusedError("a"), ConnectionRefusedError("b"), unstable,
                        ConnectionRefusedError("c"), FakeWS(HANG))
    feed2 = WebSocketFeed(BinanceAdapter(), BINANCE, clock2, connect=conn2, sleep=sleeps2, stable_after_s=10.0)
    await collect(feed2, lambda evs: sum(isinstance(e, FeedStatus) and e.connected for e in evs) >= 2)
    assert sleeps2.delays == [jit(0.5, R0[0]), jit(1.0, R0[1]), jit(2.0, R0[2]), jit(4.0, R0[3])]


def test_backoff_delay_is_capped_and_deterministic_per_seed() -> None:
    def make(seed: int) -> WebSocketFeed:
        return WebSocketFeed(BinanceAdapter(), BINANCE, SimClock(), connect=FakeConnect(),
                             max_backoff_s=4.0, initial_backoff_s=0.5, seed=seed)

    a, b, c = make(42), make(42), make(43)
    seq_a = [a.backoff_delay(n) for n in range(8)]
    assert seq_a == [b.backoff_delay(n) for n in range(8)]
    assert seq_a != [c.backoff_delay(n) for n in range(8)]
    assert seq_a[0] == 0.5 * (0.5 + 0.5 * 0.6394267984578837)
    assert seq_a[1] == 1.0 * (0.5 + 0.5 * 0.025010755222666936)
    for n, d in enumerate(seq_a):
        cap = min(4.0, 0.5 * 2**n)
        assert cap / 2 <= d <= cap
    assert 2.0 <= a.backoff_delay(10_000) <= 4.0


async def test_stall_timeout_drops_and_reconnects() -> None:
    clock = SimClock(0.0)
    silent = FakeWS(HANG)
    conn = FakeConnect(silent, FakeWS(binance_frame(7), HANG))
    feed = WebSocketFeed(BinanceAdapter(), BINANCE, clock, connect=conn, sleep=Sleeps(), stall_timeout_s=0.05)
    events = await collect(feed, n_quotes(1))
    assert summary(events) == [
        ("status", True, ""),
        ("status", False, "stall: no message for 0.05s"),
        ("status", True, ""),
        ("quote", "BTC-USDT", 7),
        ("status", False, "stopped"),
    ]
    assert silent.closed
    assert feed.stats.last_error == "stall: no message for 0.05s"


async def test_parse_errors_are_counted_and_never_fatal() -> None:
    ws = FakeWS("not json", binance_frame(1), '{"foo": 1}', b"\xff\xfe", binance_frame(2), HANG)
    feed = WebSocketFeed(BinanceAdapter(), BINANCE, SimClock(), connect=FakeConnect(ws), sleep=Sleeps())
    events = await collect(feed, n_quotes(2))
    assert summary(events) == [
        ("status", True, ""),
        ("quote", "BTC-USDT", 1),
        ("quote", "BTC-USDT", 2),
        ("status", False, "stopped"),
    ]
    assert (feed.stats.parse_errors, feed.stats.messages, feed.stats.connects) == (3, 5, 1)
    assert feed.stats.last_error.startswith("parse:")


class FastPingBinance(BinanceAdapter):
    def heartbeat(self) -> tuple[float, str] | None:
        return (0.01, "PING")


async def _wait_until(cond: Callable[[], bool], timeout: float = 2.0) -> None:
    async def poll() -> None:
        while not cond():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), timeout)


async def test_heartbeat_is_sent_while_connected_and_stops_after() -> None:
    ws = FakeWS(HANG)
    feed = WebSocketFeed(FastPingBinance(), BINANCE, SimClock(), connect=FakeConnect(ws), sleep=Sleeps())
    agen = feed.stream()
    first = await anext(agen)
    assert first == FeedStatus("binance", True, 0.0)
    await _wait_until(lambda: ws.sent.count("PING") >= 3)
    feed.stop()
    rest = [ev async for ev in agen]
    assert summary(rest) == [("status", False, "stopped")]
    sent = len(ws.sent)
    await asyncio.sleep(0.05)
    assert len(ws.sent) == sent  # the heartbeat task is gone with the connection
    assert feed.stats.heartbeats_sent == sent >= 3


async def test_bybit_app_ping_follows_subscription() -> None:
    ws = FakeWS(HANG)
    feed = WebSocketFeed(BybitAdapter(ping_interval_s=0.01), BYBIT, SimClock(), connect=FakeConnect(ws), sleep=Sleeps())
    agen = feed.stream()
    await anext(agen)
    await _wait_until(lambda: len(ws.sent) >= 3)
    feed.stop()
    _ = [ev async for ev in agen]
    assert ws.sent[0] == '{"op":"subscribe","args":["orderbook.1.BTCUSDT"]}'
    assert set(ws.sent[1:]) == {'{"op":"ping"}'}


BYBIT_PONG = fixture_lines("bybit_control.jsonl")[1]  # real {"success":true,"ret_msg":"pong",...}


async def _run_quiet_bybit(answer_pings: bool) -> tuple[list[FeedEvent], WebSocketFeed, FakeWS]:
    """A connection with no market data for 0.6 s, stall timeout 0.2 s, default 20 s Bybit ping."""
    first = FakeWS(HANG, respond=(lambda m: BYBIT_PONG if m == '{"op":"ping"}' else None) if answer_pings else None)
    feed = WebSocketFeed(BybitAdapter(), BYBIT, SimClock(), connect=FakeConnect(first, FakeWS(HANG)),
                         sleep=Sleeps(), stall_timeout_s=0.2)
    events: list[FeedEvent] = []

    async def consume() -> None:
        async for ev in feed.stream():
            events.append(ev)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.6)
    feed.stop()
    await asyncio.wait_for(task, 2.0)
    return events, feed, first


async def test_app_pings_keep_a_quiet_connection_alive() -> None:
    events, feed, ws = await _run_quiet_bybit(answer_pings=True)
    assert feed.heartbeat_interval_s == 0.1  # min(20 s, stall_timeout_s / 2)
    assert summary(events) == [("status", True, ""), ("status", False, "stopped")]
    assert ws.sent.count('{"op":"ping"}') >= 3
    assert feed.stats.messages >= 3 and feed.stats.parse_errors == 0


async def test_unanswered_pings_still_hit_the_stall_timeout() -> None:
    events, feed, ws = await _run_quiet_bybit(answer_pings=False)
    assert summary(events)[:3] == [
        ("status", True, ""),
        ("status", False, "stall: no message for 0.2s"),
        ("status", True, ""),
    ]
    assert ws.closed and feed.stats.connects == 2


async def test_sequence_regression_emits_resync_so_the_book_accepts_new_sequence() -> None:
    def snap(u: int, bid: str) -> str:
        return _bybit("snapshot", u, [[bid, "1"]], [["101", "1"]])

    ws = FakeWS(snap(100, "100.0"), snap(101, "100.1"), snap(1, "100.2"), HANG)  # u=1: Bybit service restart
    feed = WebSocketFeed(BybitAdapter(), BYBIT, SimClock(), connect=FakeConnect(ws), sleep=Sleeps())
    events = await collect(feed, n_quotes(3))
    assert summary(events) == [
        ("status", True, ""),
        ("quote", "BTC-USDT", 100),
        ("quote", "BTC-USDT", 101),
        ("status", False, "seq_reset BTC-USDT 101->1"),
        ("status", True, "resync"),
        ("quote", "BTC-USDT", 1),
        ("status", False, "stopped"),
    ]
    assert feed.stats.seq_resets == 1

    book, naive = QuoteBook(), QuoteBook()
    for ev in events[:-1]:
        if isinstance(ev, FeedStatus):
            if not ev.connected:
                book.invalidate_venue(ev.venue)
        else:
            book.update(ev)
            naive.update(ev)
    assert book.get("bybit_spot", "BTC-USDT").bid == 100.2
    assert naive.get("bybit_spot", "BTC-USDT").bid == 100.1  # without the resync the new sequence is rejected


async def test_stop_interrupts_backoff_wait() -> None:
    feed = WebSocketFeed(BinanceAdapter(), BINANCE, SimClock(), connect=FakeConnect(),
                         initial_backoff_s=30.0, max_backoff_s=30.0)
    events: list[FeedEvent] = []

    async def run() -> None:
        async for ev in feed.stream():
            events.append(ev)
            feed.stop()

    await asyncio.wait_for(run(), timeout=1.0)  # the 15-30 s backoff wait is cut short
    assert summary(events) == [("status", False, "connect failed: ConnectionRefusedError: script exhausted")]


async def test_stopped_feed_yields_nothing() -> None:
    feed = WebSocketFeed(BinanceAdapter(), BINANCE, SimClock(), connect=FakeConnect(FakeWS(HANG)))
    feed.stop()
    assert [ev async for ev in feed.stream()] == []


def test_feed_rejects_bad_settings() -> None:
    for kw in ({"stall_timeout_s": 0}, {"initial_backoff_s": 0}, {"initial_backoff_s": 5, "max_backoff_s": 1}):
        with pytest.raises(ValueError):
            WebSocketFeed(BinanceAdapter(), BINANCE, SimClock(), connect=FakeConnect(), **kw)


# ---------------------------------------------------------------------------
# merge_feeds


class ListFeed:
    def __init__(self, venue: str, events: list[FeedEvent], *, then: str = "end", gap: float = 0.0) -> None:
        self.venue = venue
        self.events = events
        self.then = then  # "end" | "hang" | "raise"
        self.gap = gap
        self.closed = False

    async def stream(self) -> AsyncIterator[FeedEvent]:
        try:
            for ev in self.events:
                await asyncio.sleep(self.gap)
                yield ev
            if self.then == "hang":
                await asyncio.Event().wait()
            elif self.then == "raise":
                raise RuntimeError(f"{self.venue} exploded")
        finally:
            self.closed = True


def q(venue: str, t: float) -> Quote:
    return Quote(venue, "BTC-USDT", 100.0, 1.0, 101.0, 1.0, t)


async def test_merge_feeds_fans_in_every_event_in_per_feed_order() -> None:
    a = ListFeed("a", [q("a", i) for i in range(50)])
    b = ListFeed("b", [FeedStatus("b", True, 0.0)] + [q("b", i) for i in range(30)])
    got = await asyncio.wait_for(_drain(merge_feeds([a, b], maxsize=2)), 5.0)
    assert len(got) == 81
    assert [e for e in got if e.venue == "a"] == a.events
    assert [e for e in got if e.venue == "b"] == b.events
    assert a.closed and b.closed


async def _drain(it: AsyncIterator[FeedEvent]) -> list[FeedEvent]:
    return [ev async for ev in it]


async def test_merge_feeds_propagates_feed_errors_and_cancels_the_rest() -> None:
    a = ListFeed("a", [q("a", 1)], then="hang")
    b = ListFeed("b", [q("b", 1)], then="raise", gap=0.01)
    with pytest.raises(RuntimeError, match="b exploded"):
        await asyncio.wait_for(_drain(merge_feeds([a, b])), 5.0)
    assert a.closed and b.closed


async def test_merge_feeds_consumer_exit_closes_feeds() -> None:
    a = ListFeed("a", [q("a", i) for i in range(5)], then="hang")
    b = ListFeed("b", [q("b", i) for i in range(5)], then="hang")
    merged = merge_feeds([a, b])
    got = [await anext(merged) for _ in range(3)]
    await merged.aclose()
    assert len(got) == 3
    assert a.closed and b.closed


# ---------------------------------------------------------------------------
# live smoke test (network): ARBBOT_LIVE_TESTS=1 python -m pytest tests/test_feeds.py -k live


@pytest.mark.skipif(os.environ.get("ARBBOT_LIVE_TESTS") != "1", reason="set ARBBOT_LIVE_TESTS=1 to hit Binance")
async def test_live_binance_feed_receives_a_quote() -> None:
    clock = WallClock()
    venue = venue_cfg("binance", "binance", inst("BTC-USDT", "BTCUSDT"))
    feed = WebSocketFeed(new_adapter("binance"), venue, clock, stall_timeout_s=15.0)
    events = await asyncio.wait_for(_until_quote(feed), timeout=30.0)
    quote = events[-1]
    assert isinstance(quote, Quote)
    assert events[0] == FeedStatus("binance", True, events[0].ts_local)
    assert (quote.venue, quote.symbol) == ("binance", "BTC-USDT")
    assert quote.is_valid() and quote.seq is not None and quote.seq > 0
    assert abs(quote.ts_local - clock.now()) < 30.0


async def _until_quote(feed: WebSocketFeed) -> list[FeedEvent]:
    events: list[FeedEvent] = []
    agen = feed.stream()
    try:
        async for ev in agen:
            events.append(ev)
            if isinstance(ev, Quote):
                return events
    finally:
        feed.stop()
        await agen.aclose()
    return events


# --------------------------------------------------------------------------- review findings (regressions)


def test_bybit_reconfirmation_with_the_same_u_refreshes_the_quote() -> None:
    """Live capture (BTCEUR, orderbook.1): Bybit re-sends an unchanged snapshot every few seconds with
    the same ``u``. It confirms the book is still current, so it must not be dropped as out of order
    (which would let an unchanged book go stale after max_quote_age)."""
    frames = [json.loads(line) for line in (FIXTURES / "bybit_reconfirm.jsonl").read_text().splitlines()]
    adapter, book = BybitAdapter(), QuoteBook()
    quotes = [q for f in frames for q in adapter.parse(f["raw"], f["t"], {"BTCEUR": "BTC-USD"})]
    first, again, changed = quotes
    assert first.seq == again.seq == 10248779 and changed.seq == 10248780
    assert again.ts_local - first.ts_local > 5.0  # older than a 1.5 s staleness limit by then
    assert book.update(first) and book.update(again)
    assert book.fresh("bybit", "BTC-USD", again.ts_local, 1.5) == again  # refreshed
    assert book.update(changed)

    # Still rejected: a lower seq, or the same seq with a different book (or an older timestamp).
    assert not book.update(first)
    moved = Quote("bybit", "BTC-USD", 71571.0, 0.003755, 71602.3, 0.1, changed.ts_local + 1, seq=changed.seq)
    assert not book.update(moved)
    stale_copy = Quote("bybit", "BTC-USD", changed.bid, changed.bid_size, changed.ask, changed.ask_size,
                       changed.ts_local - 1, seq=changed.seq)
    assert not book.update(stale_copy)
    assert book.get("bybit", "BTC-USD") == changed
