"""Per-venue websocket adapters: endpoint, subscription, heartbeat and frame parsing.

Every adapter turns one raw websocket frame into zero or more top-of-book
``Quote`` objects. Control frames (subscription acks, pongs, heartbeats,
status) return ``[]``. Malformed frames, and frames in which the venue reports
an error, raise ``ValueError``; the feed logs and counts those and keeps going.

Formats were checked on 2026-10-27 against each venue's official docs and,
where reachable, a live frame (``tests/fixtures/<venue>_frame.json``):

* Binance  -- ``<symbol>@bookTicker`` on the market-data-only host
  ``wss://data-stream.binance.vision`` (combined streams wrap each payload as
  ``{"stream", "data"}``). Payload ``{u, s, b, B, a, A}``: no event time, so
  ``seq = u`` and ``ts_exchange = None``. The server sends protocol-level
  pings every 20 s (answered by the websocket library), so no app heartbeat.
* Bybit    -- v5 public spot ``orderbook.1.<SYM>``. Docs: level 1 is pushed as
  ``snapshot`` messages; a delta that omits a side keeps the last known side.
  ``u`` resets to 1 when Bybit restarts the service (the feed resyncs on a
  sequence regression). App heartbeat ``{"op":"ping"}`` every 20 s.
* Kraken   -- v2 ``ticker`` with ``event_trigger: "bbo"`` so updates fire on
  best-bid/offer changes instead of trades. The server sends a
  ``{"channel":"heartbeat"}`` frame every second when idle; no client ping.
* Coinbase -- Advanced Trade ``ticker`` channel, ``events[].tickers[]`` with
  ``best_bid``/``best_bid_quantity``/``best_ask``/``best_ask_quantity``. Ticker
  updates fire on trades, not on every book change. The ``heartbeats``
  channel must be subscribed or idle subscriptions close within 60-90 s.
  ``sequence_num`` is per connection.
* OKX      -- v5 public ``bbo-tbt`` (tick-by-tick best bid/offer). Implemented
  from the docs only (the host resets connections from the build sandbox).
  Entries are ``[price, size, "0", order_count]``; ``seqId`` may reset during
  maintenance. The docs require a text ``ping`` when idle for N < 30 s.
"""

from __future__ import annotations

import dataclasses
import json
import math
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from ..config import InstrumentConfig
from ..models import Quote

__all__ = [
    "ADAPTERS",
    "BinanceAdapter",
    "BybitAdapter",
    "CoinbaseAdapter",
    "KrakenAdapter",
    "OkxAdapter",
    "VenueAdapter",
    "new_adapter",
    "parse_rfc3339",
]


class VenueAdapter(ABC):
    """How to talk to one venue's public top-of-book websocket."""

    name: str = ""

    @abstractmethod
    def url(self, instruments: Sequence[InstrumentConfig]) -> str:
        """Websocket URL (may itself carry the subscription, as Binance's does)."""

    def subscribe_messages(self, instruments: Sequence[InstrumentConfig]) -> list[str]:
        """JSON text frames to send right after connecting (empty when the URL subscribes)."""
        return []

    def heartbeat(self) -> tuple[float, str] | None:
        """(interval seconds, app-level ping text) for venues that need a client ping."""
        return None

    @abstractmethod
    def parse(self, raw: str | bytes, now: float, symbols: Mapping[str, str]) -> list[Quote]:
        """Quotes in ``raw``; ``symbols`` maps venue symbol -> canonical symbol.

        Quotes for symbols missing from ``symbols`` are skipped, not errors.
        """

    def reset(self) -> None:
        """Forget per-connection state. The feed calls this on every (re)connect."""


# ---------------------------------------------------------------------------
# shared helpers


def _loads(raw: str | bytes) -> Any:
    text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
    return json.loads(text)  # JSONDecodeError and UnicodeDecodeError are ValueErrors


def _obj(x: Any, what: str) -> dict[str, Any]:
    if not isinstance(x, dict):
        raise ValueError(f"{what}: expected a JSON object, got {type(x).__name__}")
    return x


def _list(x: Any, what: str) -> list[Any]:
    if not isinstance(x, list):
        raise ValueError(f"{what}: expected a JSON array, got {type(x).__name__}")
    return x


def _field(d: Mapping[str, Any], key: str, what: str) -> Any:
    try:
        return d[key]
    except KeyError:
        raise ValueError(f"{what}: missing field {key!r}") from None


def _num(x: Any, what: str) -> float:
    """Finite float from a JSON number or numeric string."""
    if isinstance(x, bool) or not isinstance(x, (int, float, str)):
        raise ValueError(f"{what}: expected a number, got {x!r}")
    try:
        v = float(x)
    except ValueError:
        raise ValueError(f"{what}: not a number: {x!r}") from None
    if not math.isfinite(v):
        raise ValueError(f"{what}: not finite: {x!r}")
    return v


def _int(x: Any, what: str) -> int:
    if isinstance(x, bool) or not isinstance(x, (int, str)):
        raise ValueError(f"{what}: expected an integer, got {x!r}")
    try:
        return int(x)
    except ValueError:
        raise ValueError(f"{what}: not an integer: {x!r}") from None


def _canonical(symbols: Mapping[str, str], venue_symbol: str) -> str | None:
    hit = symbols.get(venue_symbol)
    if hit is not None:
        return hit
    folded = venue_symbol.casefold()
    for k, v in symbols.items():
        if k.casefold() == folded:
            return v
    return None


_RFC3339 = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[Tt ](\d{2}:\d{2}:\d{2})(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$"
)


def parse_rfc3339(s: Any) -> float:
    """RFC 3339 timestamp -> epoch seconds, keeping any number of fractional digits."""
    if not isinstance(s, str):
        raise ValueError(f"timestamp: expected a string, got {s!r}")
    m = _RFC3339.match(s)
    if m is None:
        raise ValueError(f"timestamp: not RFC 3339: {s!r}")
    date, clock, frac, tz = m.groups()
    offset = "+00:00" if tz in ("Z", "z") else tz
    whole = datetime.fromisoformat(f"{date}T{clock}{offset}").timestamp()
    return whole + (float("0" + frac) if frac else 0.0)


def _compact(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"))


def _require_instruments(instruments: Sequence[InstrumentConfig], venue: str) -> None:
    if not instruments:
        raise ValueError(f"{venue}: at least one instrument is required")


# ---------------------------------------------------------------------------
# Binance


class BinanceAdapter(VenueAdapter):
    """Spot ``<symbol>@bookTicker`` via combined streams on the market-data host."""

    name = "binance"
    MAX_STREAMS = 1024  # per connection (docs: WebSocket Limits)

    def __init__(self, base_url: str = "wss://data-stream.binance.vision") -> None:
        self.base_url = base_url.rstrip("/")

    def url(self, instruments: Sequence[InstrumentConfig]) -> str:
        _require_instruments(instruments, self.name)
        if len(instruments) > self.MAX_STREAMS:
            raise ValueError(f"binance: at most {self.MAX_STREAMS} streams per connection")
        streams = "/".join(f"{i.venue_symbol.lower()}@bookTicker" for i in instruments)
        return f"{self.base_url}/stream?streams={streams}"

    def parse(self, raw: str | bytes, now: float, symbols: Mapping[str, str]) -> list[Quote]:
        msg = _obj(_loads(raw), "binance frame")
        payload = _obj(msg["data"], "binance data") if "stream" in msg and "data" in msg else msg
        if "u" in payload and "s" in payload:
            vs = payload["s"]
            if not isinstance(vs, str):
                raise ValueError(f"binance: bad symbol {vs!r}")
            canonical = _canonical(symbols, vs)
            if canonical is None:
                return []
            return [
                Quote(
                    venue=self.name,
                    symbol=canonical,
                    bid=_num(_field(payload, "b", "binance"), "binance b"),
                    bid_size=_num(_field(payload, "B", "binance"), "binance B"),
                    ask=_num(_field(payload, "a", "binance"), "binance a"),
                    ask_size=_num(_field(payload, "A", "binance"), "binance A"),
                    ts_local=now,
                    ts_exchange=None,  # bookTicker carries no event time
                    seq=_int(payload["u"], "binance u"),
                )
            ]
        if payload.get("e") == "serverShutdown":
            return []  # the server is about to close; the feed reconnects
        if "result" in msg and "id" in msg:
            return []  # SUBSCRIBE / UNSUBSCRIBE ack
        if "error" in msg or ("code" in msg and "msg" in msg):
            err = msg.get("error", msg)
            raise ValueError(f"binance error: {err}")
        raise ValueError(f"binance: unrecognized frame {str(raw)[:200]}")


# ---------------------------------------------------------------------------
# Bybit


Level = tuple[float, float]  # (price, size)


def _levels(x: Any, what: str) -> list[Level]:
    out = []
    for entry in _list(x, what):
        e = _list(entry, what)
        if len(e) < 2:
            raise ValueError(f"{what}: level needs [price, size], got {entry!r}")
        out.append((_num(e[0], f"{what} price"), _num(e[1], f"{what} size")))
    return out


class BybitAdapter(VenueAdapter):
    """v5 public spot ``orderbook.1.<SYM>``; keeps the last known side across deltas.

    Stateful (last best bid/ask per symbol), so use one instance per connection
    (``new_adapter("bybit")``); the feed calls ``reset()`` on every connect.
    """

    name = "bybit"
    MAX_ARGS_PER_REQUEST = 10  # docs: spot accepts up to 10 args per subscribe request

    def __init__(
        self, url: str = "wss://stream.bybit.com/v5/public/spot", ping_interval_s: float = 20.0
    ) -> None:
        self._url = url
        self.ping_interval_s = ping_interval_s
        self._books: dict[str, tuple[Level | None, Level | None]] = {}

    def url(self, instruments: Sequence[InstrumentConfig]) -> str:
        _require_instruments(instruments, self.name)
        return self._url

    def subscribe_messages(self, instruments: Sequence[InstrumentConfig]) -> list[str]:
        _require_instruments(instruments, self.name)
        topics = [f"orderbook.1.{i.venue_symbol}" for i in instruments]
        n = self.MAX_ARGS_PER_REQUEST
        return [_compact({"op": "subscribe", "args": topics[k : k + n]}) for k in range(0, len(topics), n)]

    def heartbeat(self) -> tuple[float, str] | None:
        return (self.ping_interval_s, _compact({"op": "ping"}))

    def reset(self) -> None:
        self._books.clear()

    def parse(self, raw: str | bytes, now: float, symbols: Mapping[str, str]) -> list[Quote]:
        msg = _obj(_loads(raw), "bybit frame")
        topic = msg.get("topic")
        if topic is not None:
            if not isinstance(topic, str) or not topic.startswith("orderbook."):
                raise ValueError(f"bybit: unexpected topic {topic!r}")
            return self._orderbook(msg, now, symbols)
        if "op" in msg:  # subscribe ack, pong ("op":"ping" or "op":"pong")
            if msg.get("success") is False:
                raise ValueError(f"bybit {msg.get('op')} failed: {msg.get('ret_msg')}")
            return []
        raise ValueError(f"bybit: unrecognized frame {str(raw)[:200]}")

    def _orderbook(self, msg: dict[str, Any], now: float, symbols: Mapping[str, str]) -> list[Quote]:
        kind = msg.get("type")
        if kind not in ("snapshot", "delta"):
            raise ValueError(f"bybit: bad orderbook type {kind!r}")
        data = _obj(_field(msg, "data", "bybit"), "bybit data")
        vs = _field(data, "s", "bybit data")
        if not isinstance(vs, str):
            raise ValueError(f"bybit: bad symbol {vs!r}")
        bids = _levels(data.get("b", []), "bybit b")
        asks = _levels(data.get("a", []), "bybit a")
        seq = _int(_field(data, "u", "bybit data"), "bybit u")
        ts_ms = msg.get("cts", msg.get("ts"))  # cts = matching-engine time, ts = push time
        ts_exchange = _num(ts_ms, "bybit ts") / 1000.0 if ts_ms is not None else None
        canonical = _canonical(symbols, vs)
        if canonical is None:
            return []
        if kind == "snapshot":
            # A snapshot is the full level-1 state: an empty side really is empty.
            bid = max(((p, s) for p, s in bids if s > 0), default=None)
            ask = min(((p, s) for p, s in asks if s > 0), default=None)
        else:
            prev_bid, prev_ask = self._books.get(vs, (None, None))
            bid = self._apply_delta(prev_bid, bids, best=max)
            ask = self._apply_delta(prev_ask, asks, best=min)
        self._books[vs] = (bid, ask)
        if bid is None or ask is None:
            return []
        return [
            Quote(
                venue=self.name,
                symbol=canonical,
                bid=bid[0],
                bid_size=bid[1],
                ask=ask[0],
                ask_size=ask[1],
                ts_local=now,
                ts_exchange=ts_exchange,
                seq=seq,
            )
        ]

    @staticmethod
    def _apply_delta(cur: Level | None, levels: list[Level], best: Any) -> Level | None:
        """Level-1 delta: omitted side keeps ``cur``; a non-zero level is the new top;
        a zero-size level at the current price deletes it."""
        if not levels:
            return cur
        live = [lv for lv in levels if lv[1] > 0]
        if live:
            return best(live, key=lambda lv: lv[0])
        if cur is not None and any(p == cur[0] for p, _ in levels):
            return None
        return cur


# ---------------------------------------------------------------------------
# Kraken


class KrakenAdapter(VenueAdapter):
    """Spot v2 ``ticker`` channel with ``event_trigger: "bbo"``."""

    name = "kraken"

    def __init__(self, url: str = "wss://ws.kraken.com/v2") -> None:
        self._url = url

    def url(self, instruments: Sequence[InstrumentConfig]) -> str:
        _require_instruments(instruments, self.name)
        return self._url

    def subscribe_messages(self, instruments: Sequence[InstrumentConfig]) -> list[str]:
        _require_instruments(instruments, self.name)
        params = {
            "channel": "ticker",
            "symbol": [i.venue_symbol for i in instruments],
            "event_trigger": "bbo",
            "snapshot": True,
        }
        return [_compact({"method": "subscribe", "params": params})]

    def parse(self, raw: str | bytes, now: float, symbols: Mapping[str, str]) -> list[Quote]:
        msg = _obj(_loads(raw), "kraken frame")
        channel = msg.get("channel")
        if channel == "ticker":
            if msg.get("type") not in ("snapshot", "update"):
                raise ValueError(f"kraken: bad ticker type {msg.get('type')!r}")
            quotes = []
            for item in _list(_field(msg, "data", "kraken"), "kraken data"):
                item = _obj(item, "kraken ticker")
                vs = _field(item, "symbol", "kraken ticker")
                if not isinstance(vs, str):
                    raise ValueError(f"kraken: bad symbol {vs!r}")
                ts = item.get("timestamp")
                q = Quote(
                    venue=self.name,
                    symbol=vs,  # replaced below once validated
                    bid=_num(_field(item, "bid", "kraken"), "kraken bid"),
                    bid_size=_num(_field(item, "bid_qty", "kraken"), "kraken bid_qty"),
                    ask=_num(_field(item, "ask", "kraken"), "kraken ask"),
                    ask_size=_num(_field(item, "ask_qty", "kraken"), "kraken ask_qty"),
                    ts_local=now,
                    ts_exchange=parse_rfc3339(ts) if ts is not None else None,
                    seq=None,
                )
                canonical = _canonical(symbols, vs)
                if canonical is not None:
                    quotes.append(_with_symbol(q, canonical))
            return quotes
        if channel in ("heartbeat", "status"):
            return []
        if "method" in msg:  # subscribe/unsubscribe ack, pong
            if msg.get("success") is False:
                raise ValueError(f"kraken {msg.get('method')} failed: {msg.get('error')}")
            return []
        if "error" in msg:
            raise ValueError(f"kraken error: {msg['error']}")
        raise ValueError(f"kraken: unrecognized frame {str(raw)[:200]}")


def _with_symbol(q: Quote, symbol: str) -> Quote:
    return dataclasses.replace(q, symbol=symbol)


# ---------------------------------------------------------------------------
# Coinbase


class CoinbaseAdapter(VenueAdapter):
    """Advanced Trade public ``ticker`` channel plus ``heartbeats`` to keep the socket open."""

    name = "coinbase"

    def __init__(self, url: str = "wss://advanced-trade-ws.coinbase.com") -> None:
        self._url = url

    def url(self, instruments: Sequence[InstrumentConfig]) -> str:
        _require_instruments(instruments, self.name)
        return self._url

    def subscribe_messages(self, instruments: Sequence[InstrumentConfig]) -> list[str]:
        _require_instruments(instruments, self.name)
        products = [i.venue_symbol for i in instruments]
        return [
            _compact({"type": "subscribe", "product_ids": products, "channel": "ticker"}),
            _compact({"type": "subscribe", "channel": "heartbeats"}),
        ]

    def parse(self, raw: str | bytes, now: float, symbols: Mapping[str, str]) -> list[Quote]:
        msg = _obj(_loads(raw), "coinbase frame")
        if msg.get("type") == "error":
            raise ValueError(f"coinbase error: {msg.get('message')}")
        channel = msg.get("channel")
        if channel == "ticker":
            ts = msg.get("timestamp")
            ts_exchange = parse_rfc3339(ts) if ts is not None else None
            sn = msg.get("sequence_num")
            seq = _int(sn, "coinbase sequence_num") if sn is not None else None
            # One message may batch several tickers for a product (cascading
            # matches); they share sequence_num, so only the last is the latest.
            latest: dict[str, Quote] = {}
            for ev in _list(_field(msg, "events", "coinbase"), "coinbase events"):
                ev = _obj(ev, "coinbase event")
                for t in _list(ev.get("tickers", []), "coinbase tickers"):
                    t = _obj(t, "coinbase ticker")
                    vs = _field(t, "product_id", "coinbase ticker")
                    if not isinstance(vs, str):
                        raise ValueError(f"coinbase: bad product_id {vs!r}")
                    q = Quote(
                        venue=self.name,
                        symbol=vs,
                        bid=_num(_field(t, "best_bid", "coinbase"), "coinbase best_bid"),
                        bid_size=_num(_field(t, "best_bid_quantity", "coinbase"), "coinbase best_bid_quantity"),
                        ask=_num(_field(t, "best_ask", "coinbase"), "coinbase best_ask"),
                        ask_size=_num(_field(t, "best_ask_quantity", "coinbase"), "coinbase best_ask_quantity"),
                        ts_local=now,
                        ts_exchange=ts_exchange,
                        seq=seq,
                    )
                    canonical = _canonical(symbols, vs)
                    if canonical is not None:
                        latest.pop(canonical, None)
                        latest[canonical] = _with_symbol(q, canonical)
            return list(latest.values())
        if channel in ("heartbeats", "subscriptions"):
            return []
        raise ValueError(f"coinbase: unrecognized frame {str(raw)[:200]}")


# ---------------------------------------------------------------------------
# OKX


class OkxAdapter(VenueAdapter):
    """v5 public ``bbo-tbt`` (tick-by-tick level 1). Spot sizes are in base currency."""

    name = "okx"

    def __init__(
        self,
        url: str = "wss://ws.okx.com/ws/v5/public",
        channel: str = "bbo-tbt",
        ping_interval_s: float = 20.0,
    ) -> None:
        if channel not in ("bbo-tbt", "books5"):
            raise ValueError(f"okx: unsupported channel {channel!r}")
        if not 0 < ping_interval_s < 30:
            raise ValueError("okx: ping interval must be < 30 s (the server drops idle connections at 30 s)")
        self._url = url
        self.channel = channel
        self.ping_interval_s = ping_interval_s

    def url(self, instruments: Sequence[InstrumentConfig]) -> str:
        _require_instruments(instruments, self.name)
        return self._url

    def subscribe_messages(self, instruments: Sequence[InstrumentConfig]) -> list[str]:
        _require_instruments(instruments, self.name)
        args = [{"channel": self.channel, "instId": i.venue_symbol} for i in instruments]
        return [_compact({"op": "subscribe", "args": args})]

    def heartbeat(self) -> tuple[float, str] | None:
        return (self.ping_interval_s, "ping")

    def parse(self, raw: str | bytes, now: float, symbols: Mapping[str, str]) -> list[Quote]:
        text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
        if text.strip() == "pong":
            return []
        msg = _obj(json.loads(text), "okx frame")
        event = msg.get("event")
        if event is not None:
            if event == "error" or (isinstance(event, str) and event.endswith("-error")):
                raise ValueError(f"okx {event} {msg.get('code')}: {msg.get('msg')}")
            return []  # subscribe/unsubscribe ack, notice, channel-conn-count
        arg = _obj(_field(msg, "arg", "okx"), "okx arg")
        if arg.get("channel") != self.channel:
            raise ValueError(f"okx: unexpected channel {arg.get('channel')!r}")
        vs = _field(arg, "instId", "okx arg")
        if not isinstance(vs, str):
            raise ValueError(f"okx: bad instId {vs!r}")
        canonical = _canonical(symbols, vs)
        quotes = []
        for item in _list(_field(msg, "data", "okx"), "okx data"):
            item = _obj(item, "okx book")
            bids = _list(_field(item, "bids", "okx book"), "okx bids")
            asks = _list(_field(item, "asks", "okx book"), "okx asks")
            ts = item.get("ts")
            seq = item.get("seqId")
            ts_exchange = _num(ts, "okx ts") / 1000.0 if ts is not None else None
            seq_v = _int(seq, "okx seqId") if seq is not None else None
            if not bids or not asks:
                continue  # keep-alive push or an empty side: nothing to quote
            bid, ask = _list(bids[0], "okx bid"), _list(asks[0], "okx ask")
            if len(bid) < 2 or len(ask) < 2:
                raise ValueError("okx: level needs [price, size, ...]")
            if canonical is None:
                continue
            quotes.append(
                Quote(
                    venue=self.name,
                    symbol=canonical,
                    bid=_num(bid[0], "okx bid px"),
                    bid_size=_num(bid[1], "okx bid sz"),
                    ask=_num(ask[0], "okx ask px"),
                    ask_size=_num(ask[1], "okx ask sz"),
                    ts_local=now,
                    ts_exchange=ts_exchange,
                    seq=seq_v,
                )
            )
        return quotes


# ---------------------------------------------------------------------------

ADAPTERS: dict[str, VenueAdapter] = {
    "binance": BinanceAdapter(),
    "bybit": BybitAdapter(),
    "kraken": KrakenAdapter(),
    "coinbase": CoinbaseAdapter(),
    "okx": OkxAdapter(),
}


def new_adapter(feed: str) -> VenueAdapter:
    """A fresh default adapter for ``feed`` (use one per connection for stateful venues)."""
    try:
        return type(ADAPTERS[feed])()
    except KeyError:
        raise KeyError(f"unknown feed {feed!r}; known: {sorted(ADAPTERS)}") from None
