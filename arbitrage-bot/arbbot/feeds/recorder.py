"""Record live quotes to JSONL (one ``Quote`` per line, every field) for replay and backtests."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
from collections.abc import Sequence
from pathlib import Path
from types import TracebackType
from typing import Any

from ..clock import Clock
from ..models import Quote
from .base import Feed
from .ws import merge_feeds

QUOTE_FIELDS: tuple[str, ...] = tuple(f.name for f in dataclasses.fields(Quote))
_DRAIN_TIMEOUT_S = 0.001


def quote_to_dict(q: Quote) -> dict[str, Any]:
    return {name: getattr(q, name) for name in QUOTE_FIELDS}


def quote_to_json(q: Quote) -> str:
    """Compact JSON; floats use repr so they load back bit-identical. NaN/inf are refused."""
    return json.dumps(quote_to_dict(q), separators=(",", ":"), allow_nan=False)


class QuoteRecorder:
    """Appends quotes to a JSONL file (``append=False`` truncates it first)."""

    def __init__(self, path: str | os.PathLike[str], *, append: bool = True, flush_every: int = 100) -> None:
        if flush_every < 1:
            raise ValueError("flush_every must be >= 1")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: Any = self.path.open("a" if append else "w", encoding="utf-8")
        self._flush_every = flush_every
        self.count = 0

    def write(self, quote: Quote) -> None:
        if self._fh is None:
            raise ValueError("recorder is closed")
        self._fh.write(quote_to_json(quote) + "\n")
        self.count += 1
        if self.count % self._flush_every == 0:
            self._fh.flush()

    def flush(self) -> None:
        if self._fh is not None:
            self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> QuoteRecorder:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()


async def record(
    feeds: Sequence[Feed], path: str | os.PathLike[str], duration_s: float, clock: Clock
) -> int:
    """Write every quote received (``ts_local``) before ``start + duration_s``.

    Recording ends at the first event stamped at or after the deadline, or when
    the deadline passes with nothing buffered. Status events are not recorded.
    Feeds with a ``stop()`` method are stopped at the end. Returns the number
    of quotes written.
    """
    if duration_s <= 0:
        raise ValueError("duration_s must be > 0")
    deadline = clock.now() + duration_s
    merged = merge_feeds(feeds)
    with QuoteRecorder(path) as rec:
        try:
            while True:
                # Past the deadline, only drain events already queued in time.
                timeout = max(deadline - clock.now(), _DRAIN_TIMEOUT_S)
                try:
                    ev = await asyncio.wait_for(anext(merged), timeout)
                except (TimeoutError, StopAsyncIteration):
                    break
                if ev.ts_local >= deadline:
                    break
                if isinstance(ev, Quote):
                    rec.write(ev)
        finally:
            for f in feeds:
                stop = getattr(f, "stop", None)
                if callable(stop):
                    stop()
            await merged.aclose()
        return rec.count
