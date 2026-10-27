"""Load recorded quotes, answer "what was the book at time t", and synthesize demo data."""

from __future__ import annotations

import bisect
import csv
import io
import json
import math
import os
import random
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..models import Quote

REQUIRED_COLUMNS = ("venue", "symbol", "bid", "bid_size", "ask", "ask_size", "ts_local")
OPTIONAL_COLUMNS = ("ts_exchange", "seq")


def _float(v: Any, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise ValueError(f"{what}: expected a number, got {v!r}")
    try:
        x = float(v)
    except ValueError:
        raise ValueError(f"{what}: not a number: {v!r}") from None
    if not math.isfinite(x):
        raise ValueError(f"{what}: not finite: {v!r}")
    return x


def _opt_float(v: Any, what: str) -> float | None:
    return None if v is None or v == "" else _float(v, what)


def _opt_int(v: Any, what: str) -> int | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        raise ValueError(f"{what}: expected an integer, got {v!r}")
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        try:
            return int(v)
        except ValueError:
            raise ValueError(f"{what}: not an integer: {v!r}") from None
    raise ValueError(f"{what}: expected an integer, got {v!r}")


def _str(v: Any, what: str) -> str:
    if not isinstance(v, str) or not v:
        raise ValueError(f"{what}: expected a non-empty string, got {v!r}")
    return v


def quote_from_dict(d: Mapping[str, Any], where: str = "quote") -> Quote:
    """Inverse of ``recorder.quote_to_dict``. Missing optional fields become None."""
    missing = [c for c in REQUIRED_COLUMNS if c not in d]
    if missing:
        raise ValueError(f"{where}: missing fields {missing}")
    return Quote(
        venue=_str(d["venue"], f"{where}.venue"),
        symbol=_str(d["symbol"], f"{where}.symbol"),
        bid=_float(d["bid"], f"{where}.bid"),
        bid_size=_float(d["bid_size"], f"{where}.bid_size"),
        ask=_float(d["ask"], f"{where}.ask"),
        ask_size=_float(d["ask_size"], f"{where}.ask_size"),
        ts_local=_float(d["ts_local"], f"{where}.ts_local"),
        ts_exchange=_opt_float(d.get("ts_exchange"), f"{where}.ts_exchange"),
        seq=_opt_int(d.get("seq"), f"{where}.seq"),
    )


def _load_jsonl(lines: Iterable[str], name: str) -> list[Quote]:
    out = []
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        where = f"{name}:{n}"
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"{where}: invalid JSON: {e}") from None
        if not isinstance(obj, dict):
            raise ValueError(f"{where}: expected a JSON object")
        out.append(quote_from_dict(obj, where))
    return out


def _load_csv(text: str, name: str) -> list[Quote]:
    reader = csv.reader(io.StringIO(text))
    header = next((row for row in reader if any(c.strip() for c in row)), None)
    if header is None:
        return []
    header = [h.strip() for h in header]
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    unknown = [c for c in header if c not in REQUIRED_COLUMNS + OPTIONAL_COLUMNS]
    if missing or unknown or len(set(header)) != len(header):
        raise ValueError(
            f"{name}: CSV header must be {','.join(REQUIRED_COLUMNS)}[,ts_exchange,seq]; "
            f"missing={missing} unknown={unknown}"
        )
    out = []
    for row in reader:
        n = reader.line_num
        if not row or all(not c.strip() for c in row):
            continue
        if len(row) != len(header):
            raise ValueError(f"{name}:{n}: expected {len(header)} columns, got {len(row)}")
        out.append(quote_from_dict({h: c.strip() for h, c in zip(header, row)}, f"{name}:{n}"))
    return out


def load_quotes(path: str | os.PathLike[str]) -> list[Quote]:
    """Quotes from a recorder JSONL file or a CSV file, stably sorted by ``ts_local``.

    The format is sniffed from the first non-blank character (``{`` = JSONL).
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    first = text.lstrip()[:1]
    if not first:
        return []
    quotes = _load_jsonl(text.splitlines(), p.name) if first == "{" else _load_csv(text, p.name)
    return sorted(quotes, key=lambda q: q.ts_local)  # sorted() is stable


class QuoteHistory:
    """Time-indexed quotes for point-in-time lookups (backtest fills use the book at arrival)."""

    def __init__(self, quotes: Iterable[Quote]) -> None:
        self._events: tuple[Quote, ...] = tuple(sorted(quotes, key=lambda q: q.ts_local))
        self._quotes: dict[tuple[str, str], list[Quote]] = {}
        self._times: dict[tuple[str, str], list[float]] = {}
        for q in self._events:
            key = (q.venue, q.symbol)
            self._quotes.setdefault(key, []).append(q)
            self._times.setdefault(key, []).append(q.ts_local)

    def as_of(self, venue: str, symbol: str, t: float) -> Quote | None:
        """Latest quote for (venue, symbol) with ``ts_local <= t``; on equal
        timestamps the one that came last in input order. None before the first."""
        times = self._times.get((venue, symbol))
        if not times:
            return None
        i = bisect.bisect_right(times, t)
        return self._quotes[(venue, symbol)][i - 1] if i else None

    def events(self) -> Sequence[Quote]:
        """Every quote, ordered by ``ts_local`` (stable for ties)."""
        return self._events

    def keys(self) -> list[tuple[str, str]]:
        return list(self._quotes)

    def __len__(self) -> int:
        return len(self._events)

    @property
    def start(self) -> float:
        if not self._events:
            raise ValueError("empty QuoteHistory has no start")
        return self._events[0].ts_local

    @property
    def end(self) -> float:
        if not self._events:
            raise ValueError("empty QuoteHistory has no end")
        return self._events[-1].ts_local


def generate_synthetic(
    venues: Sequence[str],
    symbol: str,
    *,
    start_ts: float,
    duration_s: float,
    hz: float,
    base_price: float,
    vol_bps: float,
    spread_bps: float,
    depth: float,
    dislocation_rate: float,
    dislocation_bps: float,
    seed: int,
) -> list[Quote]:
    """Deterministic synthetic quotes for demos and tests (same seed -> identical list).

    * A log-normal random walk shared by all venues, ``vol_bps`` per sqrt(second).
    * Per-venue noise around it, N(0, spread_bps / 4) bps, redrawn every step.
    * Each step every venue quotes ``mid -/+ spread_bps / 2`` with sizes
      uniform in [depth / 2, 3 * depth / 2], at ``start_ts + step / hz`` plus a
      fixed per-venue offset inside the step (so ``ts_local`` never ties).
    * Dislocations start at ``dislocation_rate`` per second (when none is
      active): one random venue's mid shifts by +/-``dislocation_bps`` for a
      random 0.2-1.0 s.
    Quotes are always valid: bid < ask and sizes > 0.
    """
    if not venues or len(set(venues)) != len(venues):
        raise ValueError("venues must be non-empty and unique")
    for name, v in (("duration_s", duration_s), ("hz", hz), ("base_price", base_price),
                    ("spread_bps", spread_bps), ("depth", depth)):
        if not (math.isfinite(v) and v > 0):
            raise ValueError(f"{name} must be > 0")
    for name, v in (("vol_bps", vol_bps), ("dislocation_rate", dislocation_rate),
                    ("dislocation_bps", dislocation_bps)):
        if not (math.isfinite(v) and v >= 0):
            raise ValueError(f"{name} must be >= 0")
    if spread_bps >= 2e4:
        raise ValueError("spread_bps must be < 20000 (bid would be <= 0)")

    rng = random.Random(seed)
    dt = 1.0 / hz
    steps = int(duration_s * hz)
    step_sd = vol_bps / 1e4 * math.sqrt(dt)
    noise_sd = spread_bps / 4.0
    half_spread = spread_bps / 2.0 / 1e4
    n = len(venues)
    log_mid = math.log(base_price)
    disloc_venue = -1
    disloc_bps = 0.0
    disloc_end = -1  # last step index (inclusive) of the active dislocation
    out: list[Quote] = []
    for i in range(steps):
        if i > 0:
            log_mid += rng.gauss(0.0, step_sd)
        if i > disloc_end and dislocation_rate > 0 and rng.random() < dislocation_rate * dt:
            disloc_venue = rng.randrange(n)
            disloc_bps = dislocation_bps if rng.random() < 0.5 else -dislocation_bps
            disloc_end = i + max(1, round(rng.uniform(0.2, 1.0) * hz)) - 1
        shared = math.exp(log_mid)
        for k, venue in enumerate(venues):
            bps = rng.gauss(0.0, noise_sd)
            if k == disloc_venue and i <= disloc_end:
                bps += disloc_bps
            mid = shared * math.exp(bps / 1e4)
            bid, ask = mid * (1.0 - half_spread), mid * (1.0 + half_spread)
            if not bid < ask:  # a sub-ulp spread rounds to zero: keep the book uncrossed
                bid = math.nextafter(ask, 0.0)
            out.append(
                Quote(
                    venue=venue,
                    symbol=symbol,
                    bid=bid,
                    bid_size=depth * rng.uniform(0.5, 1.5),
                    ask=ask,
                    ask_size=depth * rng.uniform(0.5, 1.5),
                    ts_local=start_ts + (i + (k + 1) / (n + 1)) * dt,
                    seq=i + 1,
                )
            )
    return out
