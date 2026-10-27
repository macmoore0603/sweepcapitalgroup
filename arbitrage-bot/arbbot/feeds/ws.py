"""Reconnecting websocket feed for one venue, and a bounded fan-in of several feeds.

``WebSocketFeed.stream()`` never ends on its own: every drop, stall or error
yields ``FeedStatus(connected=False, reason)`` (so consumers can invalidate the
venue's quotes) and then reconnects after an exponential backoff with seeded
jitter. Unparseable frames are logged and counted, never fatal.

A quote whose venue sequence number goes backwards (Bybit restarts reset
``u`` to 1, OKX maintenance resets ``seqId``) would be rejected forever by
``QuoteBook``'s out-of-order check, so the feed emits a resync pair
``FeedStatus(False, "seq_reset ...")`` / ``FeedStatus(True, "resync")`` first:
the consumer drops the old quotes and accepts the new sequence.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import random
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import websockets

from ..clock import Clock
from ..config import VenueConfig
from ..models import FeedEvent, FeedStatus
from .base import Feed
from .venues import VenueAdapter

log = logging.getLogger(__name__)

# websockets answers the server's protocol pings itself and sends its own every
# 20 s; ping_timeout bounds how long a silently dead TCP connection survives.
DEFAULT_CONNECT_KWARGS: Mapping[str, Any] = {
    "open_timeout": 10.0,
    "ping_interval": 20.0,
    "ping_timeout": 20.0,
    "close_timeout": 2.0,
}

_MAX_EXPONENT = 60  # 2.0 ** attempt stays finite; the delay is capped long before this


@dataclass(slots=True)
class FeedStats:
    connects: int = 0  # successful connect + subscribe
    disconnects: int = 0  # FeedStatus(connected=False) emitted for a failure (drop, stall, connect error)
    messages: int = 0  # frames received
    quotes: int = 0  # quotes yielded
    parse_errors: int = 0
    seq_resets: int = 0
    heartbeats_sent: int = 0
    last_error: str = ""


class WebSocketFeed:
    """One venue's quotes as a self-healing ``Feed``.

    ``connect`` is injectable (tests pass a fake); it is awaited as
    ``connect(url, **connect_kwargs)`` and must return an object with async
    ``send``, ``recv`` and ``close``. ``sleep`` (backoff waits) is injectable
    too; the default wakes early when ``stop()`` is called.

    Any frame (data, ack, pong, venue heartbeat) resets the stall timer. App
    pings go out every ``min(adapter interval, stall_timeout_s / 2)``. Venues
    without an app ping (Binance) rely on data flow: raise ``stall_timeout_s``
    for symbols whose book can sit unchanged for long.
    """

    def __init__(
        self,
        adapter: VenueAdapter,
        venue: VenueConfig,
        clock: Clock,
        *,
        connect: Callable[..., Awaitable[Any]] = websockets.connect,
        stall_timeout_s: float = 10.0,
        max_backoff_s: float = 30.0,
        seed: int = 0,
        initial_backoff_s: float = 0.5,
        stable_after_s: float = 10.0,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        connect_kwargs: Mapping[str, Any] | None = None,
    ) -> None:
        if stall_timeout_s <= 0:
            raise ValueError("stall_timeout_s must be > 0")
        if not 0 < initial_backoff_s <= max_backoff_s:
            raise ValueError("need 0 < initial_backoff_s <= max_backoff_s")
        if stable_after_s < 0:
            raise ValueError("stable_after_s must be >= 0")
        self.adapter = adapter
        self.config = venue
        self.venue = venue.name  # Feed protocol: the venue name quotes are keyed by
        self.clock = clock
        self.stall_timeout_s = stall_timeout_s
        self.max_backoff_s = max_backoff_s
        self.initial_backoff_s = initial_backoff_s
        self.stable_after_s = stable_after_s
        self.url = adapter.url(venue.instruments)
        self.stats = FeedStats()
        self._connect = connect
        self._connect_kwargs = dict(DEFAULT_CONNECT_KWARGS if connect_kwargs is None else connect_kwargs)
        self._subscribe = adapter.subscribe_messages(venue.instruments)
        self._symbols = {i.venue_symbol: i.symbol for i in venue.instruments}
        hb = adapter.heartbeat()
        if hb is not None:
            # Ping at least twice per stall window so a quiet but healthy
            # connection gets a pong before the stall timer fires.
            hb = (min(hb[0], stall_timeout_s / 2), hb[1])
        self._heartbeat = hb
        self.heartbeat_interval_s: float | None = hb[0] if hb is not None else None
        self._rng = random.Random(seed)
        self._sleep = sleep if sleep is not None else self._interruptible_sleep
        self._stop_event = asyncio.Event()
        self._ws: Any = None
        self._close_task: asyncio.Task[None] | None = None

    # -- public -------------------------------------------------------------

    def backoff_delay(self, attempt: int) -> float:
        """Delay before reconnect ``attempt`` (0-based): uniform in [d/2, d] from the
        seeded RNG, where d = min(max_backoff_s, initial_backoff_s * 2**attempt)."""
        d = min(self.max_backoff_s, self.initial_backoff_s * 2.0 ** min(attempt, _MAX_EXPONENT))
        return d * (0.5 + 0.5 * self._rng.random())

    def stop(self) -> None:
        """End ``stream()``: closes the live connection and interrupts any backoff wait."""
        self._stop_event.set()
        ws = self._ws
        if ws is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._close_task = loop.create_task(_close_quietly(ws))

    @property
    def stopped(self) -> bool:
        return self._stop_event.is_set()

    async def stream(self) -> AsyncIterator[FeedEvent]:
        attempt = 0
        while not self._stop_event.is_set():
            ws: Any = None
            hb: asyncio.Task[None] | None = None
            connected_at: float | None = None
            reason = ""
            try:
                ws = await self._connect(self.url, **self._connect_kwargs)
                self._ws = ws
                if self._stop_event.is_set():
                    break
                for msg in self._subscribe:
                    await ws.send(msg)
                self.adapter.reset()
                connected_at = self.clock.now()
                self.stats.connects += 1
                if self._heartbeat is not None:
                    hb = asyncio.create_task(self._heartbeat_loop(ws, *self._heartbeat))
                yield FeedStatus(self.venue, True, connected_at)
                last_seq: dict[str, int] = {}
                while not self._stop_event.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), self.stall_timeout_s)
                    except TimeoutError:
                        reason = f"stall: no message for {self.stall_timeout_s:g}s"
                        break
                    now = self.clock.now()
                    self.stats.messages += 1
                    try:
                        quotes = self.adapter.parse(raw, now, self._symbols)
                    except Exception as e:  # never fatal: log, count, keep reading
                        self._parse_error(e, raw)
                        continue
                    for q in quotes:
                        if q.venue != self.venue:
                            q = dataclasses.replace(q, venue=self.venue)
                        if q.seq is not None:
                            prev = last_seq.get(q.symbol)
                            if prev is not None and q.seq < prev:
                                self.stats.seq_resets += 1
                                log.warning("%s: %s sequence went back %d -> %d; resyncing",
                                            self.venue, q.symbol, prev, q.seq)
                                yield FeedStatus(self.venue, False, now, f"seq_reset {q.symbol} {prev}->{q.seq}")
                                yield FeedStatus(self.venue, True, now, "resync")
                            last_seq[q.symbol] = q.seq
                        self.stats.quotes += 1
                        yield q
            except Exception as e:
                if ws is None:
                    stage = "connect failed"
                else:
                    stage = "subscribe failed" if connected_at is None else "disconnected"
                reason = f"{stage}: {type(e).__name__}: {e}"
            finally:
                if hb is not None:
                    hb.cancel()
                    await asyncio.gather(hb, return_exceptions=True)
                self._ws = None
                if ws is not None:
                    await _close_quietly(ws)

            if self._stop_event.is_set():
                if connected_at is not None:
                    yield FeedStatus(self.venue, False, self.clock.now(), "stopped")
                return
            self.stats.disconnects += 1
            self.stats.last_error = reason
            log.warning("%s feed down (%s); reconnect attempt %d", self.venue, reason, attempt + 1)
            yield FeedStatus(self.venue, False, self.clock.now(), reason)
            if connected_at is not None and self.clock.now() - connected_at >= self.stable_after_s:
                attempt = 0  # it was a stable connection: start the backoff over
            delay = self.backoff_delay(attempt)
            attempt += 1
            await self._sleep(delay)

    # -- internals ----------------------------------------------------------

    async def _heartbeat_loop(self, ws: Any, interval: float, text: str) -> None:
        try:
            while True:
                await asyncio.sleep(interval)
                await ws.send(text)
                self.stats.heartbeats_sent += 1
        except Exception as e:  # the receive loop notices the dead connection
            log.debug("%s heartbeat stopped: %s", self.venue, e)

    async def _interruptible_sleep(self, delay: float) -> None:
        try:
            await asyncio.wait_for(self._stop_event.wait(), delay)
        except TimeoutError:
            pass

    def _parse_error(self, err: Exception, raw: Any) -> None:
        self.stats.parse_errors += 1
        self.stats.last_error = f"parse: {err}"
        n = self.stats.parse_errors
        if n <= 10 or n % 1000 == 0:
            log.warning("%s: unparseable frame #%d (%s): %.200r", self.venue, n, err, raw)


async def _close_quietly(ws: Any) -> None:
    try:
        await asyncio.wait_for(ws.close(), 5.0)
    except Exception:
        pass


# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Failed:
    venue: str
    error: Exception


_DONE = object()


async def merge_feeds(feeds: Iterable[Feed], *, maxsize: int = 10_000) -> AsyncIterator[FeedEvent]:
    """Fan several feeds into one stream through a bounded queue.

    A full queue blocks the producing feeds (backpressure; nothing is dropped,
    and staleness stays visible because ``ts_local`` is stamped on receipt).
    Ends when every feed's stream has ended. If a feed's stream raises, the
    other feeds are cancelled and the error is re-raised here.
    """
    feeds = list(feeds)
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize)

    async def pump(feed: Feed) -> None:
        it = feed.stream()
        try:
            async for ev in it:
                await queue.put(ev)
        except Exception as e:
            await queue.put(_Failed(getattr(feed, "venue", "?"), e))
            return
        finally:
            aclose = getattr(it, "aclose", None)
            if aclose is not None:
                await aclose()
        await queue.put(_DONE)

    tasks = [asyncio.create_task(pump(f)) for f in feeds]
    live = len(tasks)
    try:
        while live:
            item = await queue.get()
            if item is _DONE:
                live -= 1
            elif isinstance(item, _Failed):
                raise item.error
            else:
                yield item  # type: ignore[misc]
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
