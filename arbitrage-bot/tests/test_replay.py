"""Recorder round trip, quote loading, point-in-time history and synthetic data."""

from __future__ import annotations

import asyncio
import json
import math
import statistics
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from arbbot.clock import SimClock, WallClock
from arbbot.feeds.recorder import QUOTE_FIELDS, QuoteRecorder, quote_to_json, record
from arbbot.feeds.replay import QuoteHistory, generate_synthetic, load_quotes
from arbbot.models import FeedEvent, FeedStatus, Quote


def Q(venue: str, symbol: str, t: float, bid: float = 100.0, **kw: float | int | None) -> Quote:
    return Quote(venue=venue, symbol=symbol, bid=bid, bid_size=kw.pop("bid_size", 1.0), ask=bid + 1.0,
                 ask_size=kw.pop("ask_size", 2.0), ts_local=t, **kw)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# recorder


def test_recorder_round_trip_preserves_every_field_exactly(tmp_path: Path) -> None:
    quotes = [
        Quote("binance", "BTC-USDT", 79614.0, 6.10691, 79614.01, 1.66135, 1793096565.123456, None, 101958358644),
        Quote("bybit", "BTC-USDT", 0.1 + 0.2, 1e-9, 0.30000000000000016, 123456.789, 1.5, 1793096565.852, 1),
        Quote("kraken", "BTC-USD", 79487.5, 0.27320408, 79487.6, 0.44882569, 1.5, 1793096570.153298, None),
        Quote("coinbase", "ETH-USD", 2300.36, 1.0, 2300.48, 2.56360396, 0.25, None, 0),
    ]
    path = tmp_path / "rec" / "quotes.jsonl"
    with QuoteRecorder(path) as rec:
        for q in quotes:
            rec.write(q)
        assert rec.count == 4
    lines = path.read_text().splitlines()
    assert len(lines) == 4
    assert all(list(json.loads(ln)) == list(QUOTE_FIELDS) for ln in lines)
    assert json.loads(lines[0]) == {"venue": "binance", "symbol": "BTC-USDT", "bid": 79614.0, "bid_size": 6.10691,
                                    "ask": 79614.01, "ask_size": 1.66135, "ts_local": 1793096565.123456,
                                    "ts_exchange": None, "seq": 101958358644}
    # loaded back equal, stably sorted by ts_local (the two 1.5s keep their write order)
    assert load_quotes(path) == [quotes[3], quotes[1], quotes[2], quotes[0]]


def test_recorder_appends_by_default_and_can_truncate(tmp_path: Path) -> None:
    path = tmp_path / "q.jsonl"
    for t in (1.0, 2.0):
        with QuoteRecorder(path) as rec:
            rec.write(Q("a", "BTC-USDT", t))
    assert [q.ts_local for q in load_quotes(path)] == [1.0, 2.0]
    with QuoteRecorder(path, append=False) as rec:
        rec.write(Q("a", "BTC-USDT", 3.0))
    assert [q.ts_local for q in load_quotes(path)] == [3.0]


def test_recorder_refuses_non_finite_values_and_writes_after_close(tmp_path: Path) -> None:
    rec = QuoteRecorder(tmp_path / "q.jsonl")
    with pytest.raises(ValueError):
        rec.write(Q("a", "BTC-USDT", 1.0, bid=math.nan))
    rec.close()
    with pytest.raises(ValueError):
        rec.write(Q("a", "BTC-USDT", 1.0))
    assert quote_to_json(Q("a", "BTC-USDT", 1.0)).startswith('{"venue":"a","symbol":"BTC-USDT","bid":100.0,')


class ScriptedFeed:
    """Yields scripted events, moving the SimClock to each event's time first; then waits for stop()."""

    def __init__(self, venue: str, script: list[tuple[float, FeedEvent]], clock: SimClock) -> None:
        self.venue = venue
        self.script = script
        self.clock = clock
        self.stop_calls = 0
        self._stopped = asyncio.Event()

    def stop(self) -> None:
        self.stop_calls += 1
        self._stopped.set()

    async def stream(self) -> AsyncIterator[FeedEvent]:
        for t, ev in self.script:
            self.clock.set(t)
            yield ev
        await self._stopped.wait()


async def test_record_writes_quotes_until_the_deadline(tmp_path: Path) -> None:
    clock = SimClock(100.0)
    events: list[tuple[float, FeedEvent]] = [
        (100.0, FeedStatus("a", True, 100.0)),
        (100.5, Q("a", "BTC-USDT", 100.5)),
        (101.0, Q("b", "BTC-USDT", 101.0)),
        (101.5, FeedStatus("b", False, 101.5, "stall")),
        (102.9, Q("a", "BTC-USDT", 102.9)),
        (103.0, Q("a", "BTC-USDT", 103.0)),  # at the deadline: not recorded
        (104.0, Q("b", "BTC-USDT", 104.0)),
    ]
    feed = ScriptedFeed("a", events, clock)
    path = tmp_path / "rec.jsonl"
    n = await asyncio.wait_for(record([feed], path, 3.0, clock), 5.0)
    assert n == 3
    assert [(q.venue, q.ts_local) for q in load_quotes(path)] == [("a", 100.5), ("b", 101.0), ("a", 102.9)]
    assert feed.stop_calls == 1


async def test_record_returns_when_feeds_are_silent(tmp_path: Path) -> None:
    clock = WallClock()
    feed = ScriptedFeed("a", [], SimClock())
    n = await asyncio.wait_for(record([feed], tmp_path / "rec.jsonl", 0.05, clock), 2.0)
    assert n == 0 and feed.stop_calls == 1


# ---------------------------------------------------------------------------
# load_quotes


def test_load_csv_with_optional_columns_sorted_stably(tmp_path: Path) -> None:
    path = tmp_path / "q.csv"
    path.write_text(
        "venue,symbol,bid,bid_size,ask,ask_size,ts_local,ts_exchange,seq\n"
        "bybit,BTC-USDT,100.5,1.25,100.75,2,3.0,2.9,17\n"
        "binance,BTC-USDT,100.0,1,100.25,3,2.0,,\n"
        "\n"
        "kraken,BTC-USDT,99.5,0.5,99.75,0.25,2.0,1.95,\n"
    )
    assert load_quotes(path) == [
        Quote("binance", "BTC-USDT", 100.0, 1.0, 100.25, 3.0, 2.0, None, None),
        Quote("kraken", "BTC-USDT", 99.5, 0.5, 99.75, 0.25, 2.0, 1.95, None),
        Quote("bybit", "BTC-USDT", 100.5, 1.25, 100.75, 2.0, 3.0, 2.9, 17),
    ]


def test_load_csv_with_required_columns_only(tmp_path: Path) -> None:
    path = tmp_path / "q.csv"
    path.write_text("venue,symbol,bid,bid_size,ask,ask_size,ts_local\nokx,ETH-USDT,10,1,11,2,5.5\n")
    assert load_quotes(path) == [Quote("okx", "ETH-USDT", 10.0, 1.0, 11.0, 2.0, 5.5)]


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("venue,symbol,bid,bid_size,ask,ask_size\nokx,E-U,1,1,2,1\n", "missing"),
        ("venue,symbol,bid,bid_size,ask,ask_size,ts_local,mid\nokx,E-U,1,1,2,1,3,1.5\n", "unknown"),
        ("venue,symbol,bid,bid_size,ask,ask_size,ts_local\nokx,E-U,1,1,2,1,3\nokx,E-U,x,1,2,1,4\n", r"q\.csv:3"),
        ("venue,symbol,bid,bid_size,ask,ask_size,ts_local\nokx,E-U,1,1,2,1\n", "columns"),
        ("venue,symbol,bid,bid_size,ask,ask_size,ts_local,seq\nokx,E-U,1,1,2,1,3,1.5\n", "integer"),
        ("venue,symbol,bid,bid_size,ask,ask_size,ts_local\nokx,E-U,inf,1,2,1,3\n", "finite"),
        ("\n\nvenue,symbol,bid,bid_size,ask,ask_size,ts_local\n\nokx,E-U,1,1,2,-,3\n", r"q\.csv:5.*ask_size"),
    ],
)
def test_load_csv_rejects_bad_input(tmp_path: Path, text: str, match: str) -> None:
    path = tmp_path / "q.csv"
    path.write_text(text)
    with pytest.raises(ValueError, match=match):
        load_quotes(path)


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ('{"venue":"a","symbol":"B-C","bid":1,"bid_size":1,"ask":2,"ask_size":1}\n', r"q\.jsonl:1.*ts_local"),
        ('{"venue":"a","symbol":"B-C","bid":1,"bid_size":1,"ask":2,"ask_size":1,"ts_local":1}\n{oops\n', r"q\.jsonl:2"),
        ('{"venue":"a","symbol":"B-C","bid":"x","bid_size":1,"ask":2,"ask_size":1,"ts_local":1}\n', "bid"),
        ('{"venue":"","symbol":"B-C","bid":1,"bid_size":1,"ask":2,"ask_size":1,"ts_local":1}\n', "venue"),
    ],
)
def test_load_jsonl_rejects_bad_input(tmp_path: Path, text: str, match: str) -> None:
    path = tmp_path / "q.jsonl"
    path.write_text(text)
    with pytest.raises(ValueError, match=match):
        load_quotes(path)


def test_load_empty_files(tmp_path: Path) -> None:
    (tmp_path / "e.jsonl").write_text("\n\n")
    (tmp_path / "e.csv").write_text("")
    assert load_quotes(tmp_path / "e.jsonl") == []
    assert load_quotes(tmp_path / "e.csv") == []


# ---------------------------------------------------------------------------
# QuoteHistory


def test_quote_history_as_of_semantics() -> None:
    a1 = Q("binance", "BTC-USDT", 1.0, bid=1)
    a2 = Q("binance", "BTC-USDT", 2.0, bid=2)
    a3 = Q("binance", "BTC-USDT", 2.0, bid=3)  # same ts as a2, later in input
    a4 = Q("binance", "BTC-USDT", 4.0, bid=4)
    b1 = Q("bybit", "BTC-USDT", 1.5, bid=5)
    e1 = Q("binance", "ETH-USDT", 3.0, bid=6)
    h = QuoteHistory([a4, e1, a2, b1, a3, a1])  # unsorted input

    assert h.as_of("binance", "BTC-USDT", 0.999) is None
    assert h.as_of("binance", "BTC-USDT", 1.0) is a1
    assert h.as_of("binance", "BTC-USDT", 1.999) is a1
    assert h.as_of("binance", "BTC-USDT", 2.0) is a3
    assert h.as_of("binance", "BTC-USDT", 3.999) is a3
    assert h.as_of("binance", "BTC-USDT", 4.0) is a4
    assert h.as_of("binance", "BTC-USDT", 1e12) is a4
    assert h.as_of("bybit", "BTC-USDT", 1.499) is None
    assert h.as_of("bybit", "BTC-USDT", 1.5) is b1
    assert h.as_of("binance", "ETH-USDT", 2.999) is None
    assert h.as_of("binance", "ETH-USDT", 3.0) is e1
    assert h.as_of("okx", "BTC-USDT", 10.0) is None
    assert h.as_of("bybit", "ETH-USDT", 10.0) is None

    assert list(h.events()) == [a1, b1, a2, a3, e1, a4]
    assert (h.start, h.end, len(h)) == (1.0, 4.0, 6)
    assert sorted(h.keys()) == [("binance", "BTC-USDT"), ("binance", "ETH-USDT"), ("bybit", "BTC-USDT")]


def test_empty_quote_history() -> None:
    h = QuoteHistory([])
    assert h.as_of("binance", "BTC-USDT", 1.0) is None
    assert list(h.events()) == [] and len(h) == 0
    with pytest.raises(ValueError):
        _ = h.start
    with pytest.raises(ValueError):
        _ = h.end


# ---------------------------------------------------------------------------
# generate_synthetic

SYNTH = dict(start_ts=1000.0, duration_s=60.0, hz=10.0, base_price=50_000.0, vol_bps=5.0, spread_bps=2.0,
             depth=0.5, dislocation_rate=0.2, dislocation_bps=40.0)
VENUES = ["binance", "bybit", "okx"]


def test_synthetic_is_deterministic_per_seed() -> None:
    a = generate_synthetic(VENUES, "BTC-USDT", seed=7, **SYNTH)
    b = generate_synthetic(VENUES, "BTC-USDT", seed=7, **SYNTH)
    c = generate_synthetic(VENUES, "BTC-USDT", seed=8, **SYNTH)
    assert a == b
    assert a != c


def test_synthetic_shape_timing_and_validity() -> None:
    quotes = generate_synthetic(VENUES, "BTC-USDT", seed=1, **SYNTH)
    assert len(quotes) == 600 * 3
    ts = [q.ts_local for q in quotes]
    assert all(t0 < t1 for t0, t1 in zip(ts, ts[1:]))  # strictly increasing: no ties
    assert 1000.0 < ts[0] and ts[-1] < 1060.0
    assert ts[:3] == [1000.0 + 0.25 * 0.1, 1000.0 + 0.5 * 0.1, 1000.0 + 0.75 * 0.1]
    for venue in VENUES:
        mine = [q for q in quotes if q.venue == venue]
        assert [q.seq for q in mine] == list(range(1, 601))
        assert all(q.symbol == "BTC-USDT" for q in mine)
    for q in quotes:
        assert q.is_valid() and q.bid < q.ask
        assert 0.25 <= q.bid_size <= 0.75 and 0.25 <= q.ask_size <= 0.75
        assert q.spread_bps == pytest.approx(2.0, rel=1e-9)


def test_synthetic_without_vol_or_dislocations_stays_near_base_price() -> None:
    quiet = dict(SYNTH, vol_bps=0.0, dislocation_rate=0.0)
    quotes = generate_synthetic(VENUES, "BTC-USDT", seed=3, **quiet)
    devs = [(q.mid / 50_000.0 - 1) * 1e4 for q in quotes]
    assert max(abs(d) for d in devs) < 3.0  # venue noise is N(0, spread/4 = 0.5 bps)
    assert statistics.pstdev(devs) == pytest.approx(0.5, rel=0.1)


def _max_cross_venue_gap_bps(quotes: list[Quote], n_venues: int) -> float:
    worst = 0.0
    for i in range(0, len(quotes), n_venues):
        mids = [q.mid for q in quotes[i:i + n_venues]]
        worst = max(worst, (max(mids) - min(mids)) / min(mids) * 1e4)
    return worst


def test_synthetic_dislocations_hit_one_venue_briefly() -> None:
    calm = generate_synthetic(VENUES, "BTC-USDT", seed=5, **dict(SYNTH, dislocation_rate=0.0))
    wild = generate_synthetic(VENUES, "BTC-USDT", seed=5, **SYNTH)
    assert _max_cross_venue_gap_bps(calm, 3) < 6.0
    assert _max_cross_venue_gap_bps(wild, 3) > 35.0
    # dislocated steps are a minority: rate 0.2/s * ~0.6 s each ~ 12% of time
    steps = [quotes for quotes in (wild[i:i + 3] for i in range(0, len(wild), 3))]
    dislocated = [s for s in steps if (max(q.mid for q in s) - min(q.mid for q in s)) / s[0].mid * 1e4 > 20]
    assert 0 < len(dislocated) < len(steps) * 0.3
    for s in dislocated:  # exactly one venue is off, the other two agree
        mids = sorted(q.mid for q in s)
        gaps = sorted([(mids[1] - mids[0]) / mids[0] * 1e4, (mids[2] - mids[1]) / mids[1] * 1e4])
        assert gaps[0] < 6.0 and gaps[1] > 20.0


def test_synthetic_tiny_spread_stays_uncrossed_and_inputs_are_validated() -> None:
    quotes = generate_synthetic(["a"], "X-Y", seed=0, **dict(SYNTH, duration_s=1.0, spread_bps=1e-12))
    assert all(q.bid < q.ask for q in quotes)
    bad = [dict(SYNTH, hz=0.0), dict(SYNTH, spread_bps=0.0), dict(SYNTH, depth=-1.0),
           dict(SYNTH, vol_bps=-1.0), dict(SYNTH, dislocation_rate=math.nan)]
    for kw in bad:
        with pytest.raises(ValueError):
            generate_synthetic(VENUES, "BTC-USDT", seed=0, **kw)
    with pytest.raises(ValueError):
        generate_synthetic([], "BTC-USDT", seed=0, **SYNTH)
    with pytest.raises(ValueError):
        generate_synthetic(["a", "a"], "BTC-USDT", seed=0, **SYNTH)


def test_synthetic_feeds_quote_history() -> None:
    quotes = generate_synthetic(VENUES, "BTC-USDT", seed=2, **SYNTH)
    h = QuoteHistory(quotes)
    first_bybit = next(q for q in quotes if q.venue == "bybit")
    assert h.as_of("bybit", "BTC-USDT", first_bybit.ts_local) is first_bybit
    assert h.as_of("bybit", "BTC-USDT", first_bybit.ts_local - 1e-9) is None
    assert h.start == quotes[0].ts_local and h.end == quotes[-1].ts_local
