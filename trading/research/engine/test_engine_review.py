#!/usr/bin/env python3
"""test_engine_review.py - independent review tests of engine.py (written from ENGINE.md and DATA_NOTES.md, not from
test_engine.py).  Run:  python3 -I test_engine_review.py

Parts
  A  hand-computed fills, costs and session rules on tiny synthetic bars
  B  lookahead hunt: helpers against brute force and against truncated data, resampling, signal timing, the
     no-lookahead property on the real data (three strategies, several cuts), leaking strategies must be caught
  C  statistics: p-values, day-clustered t, bootstrap, MAE/MFE, R multiples, trades per year, the fixed split
  D  sanity strategies on the real 5-minute data with a result known in advance, and session invariants
  E  an independent plain simulator (written from the rules in ENGINE.md) against the engine on random bars
"""
import calendar
import math
import os
import sys
import tempfile
import time
import traceback
import warnings
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
from scipy import stats as sps

import engine as eng

NYZ = ZoneInfo("America/New_York")
NAN = float("nan")
TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def ts(s):
    """'YYYY-MM-DD HH:MM' New York wall clock -> epoch seconds (through zoneinfo, not through the engine)."""
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=NYZ).timestamp())


def utc(y, mo, d, h, mi):
    """A UTC wall clock -> epoch seconds without any time-zone database."""
    return calendar.timegm((y, mo, d, h, mi, 0))


def B(rows, day="2021-06-15", res=5, **kw):
    """rows: (HH:MM or 'YYYY-MM-DD HH:MM', o, h, l, c).  2021-06-15 is an ordinary Tuesday (EDT)."""
    t = [ts(r[0] if len(r[0]) > 5 else f"{day} {r[0]}") for r in rows]
    return eng.Bars(t, [r[1] for r in rows], [r[2] for r in rows], [r[3] for r in rows], [r[4] for r in rows], res, **kw)


def arr(n, d=None, fill=0.0):
    a = np.full(n, fill, dtype="float64")
    for k, v in (d or {}).items():
        a[k] = v
    return a


def mask(n, *idx):
    m = np.zeros(n, dtype=bool)
    m[list(idx)] = True
    return m


def close(a, b, tol=1e-9):
    return abs(float(a) - float(b)) <= tol


def eq_arr(a, b, tol=1e-8):
    a = np.asarray(a, dtype="float64")
    b = np.asarray(b, dtype="float64")
    if a.shape != b.shape:
        return False
    return bool(((np.isnan(a) & np.isnan(b)) | (np.abs(a - b) <= tol * np.maximum(1.0, np.abs(b)))).all())


def one_trade(res):
    assert len(res.trades) == 1, f"expected exactly one trade, got {len(res.trades)}: diag {res.diag}"
    return res.trades.iloc[0]


def et_str(x):
    return pd.Timestamp(x).strftime("%Y-%m-%d %H:%M")


_RAW = {}


def raw_1m():
    """The 1-minute file with its New York calendar, computed here through pandas (not through engine.Bars):
    dict(t, o, h, l, c, day (datetime64[D] New York date), mod (minute of day))."""
    if not _RAW:
        with np.load(eng.FILE_1M) as z:
            for k in "tohlc":
                _RAW[k] = z[k]
        loc = pd.DatetimeIndex(_RAW["t"].astype("datetime64[s]"), tz="UTC").tz_convert("America/New_York").tz_localize(None)
        sec = loc.values.astype("datetime64[s]").astype("int64")
        _RAW["day"] = (sec // 86400).astype("datetime64[D]")
        _RAW["mod"] = (sec % 86400) // 60
    return _RAW


def complete_days_1m():
    """Sorted list of 'YYYY-MM-DD' with at least 370 one-minute bars in 09:30-16:00 New York time (DATA_NOTES.md)."""
    r = raw_1m()
    m = (r["mod"] >= 570) & (r["mod"] < 960)
    d, cnt = np.unique(r["day"][m], return_counts=True)
    return [str(x) for x in d[cnt >= 370]]


# =====================================================================================================================
# A. HAND-COMPUTED FILLS, COSTS AND SESSION RULES
# =====================================================================================================================
@test
def a01_market_order_fills_at_next_open_not_at_signal_bar():
    rows = [("10:00", 100, 101, 99, 100.5),       # signal bar: nothing of this bar may be the fill
            ("10:05", 101, 103, 100.5, 102),      # entry at this open = 101
            ("10:10", 102, 104, 101, 103),        # second bar held -> max_bars=2 closes at 103
            ("10:15", 103, 105, 102, 104),
            ("10:20", 104, 104, 104, 104)]
    b = B(rows)
    tr = one_trade(eng.run(b, eng.Signals(arr(5, {0: 1}), max_bars=2)))
    assert tr.signal_bar == 0 and tr.entry_bar == 1 and tr.exit_bar == 2
    assert tr.entry_price == 101.0 and tr.exit_price == 103.0 and tr.exit_reason == "bars" and tr.order_type == "market"
    assert close(tr.gross_pts, 2.0) and close(tr.net_pts, 1.25) and tr.slippage_pts == 0.0 and tr.cost_pts == 0.75
    assert et_str(tr.entry_time) == "2021-06-15 10:05" and et_str(tr.exit_time) == "2021-06-15 10:15"
    assert tr.bars_held == 2 and tr.minutes_held == 10.0
    assert close(tr.mae_pts, 0.5) and close(tr.mfe_pts, 3.0)          # 101 - 100.5 ; 104 - 101
    assert str(tr.entry_time.tz) == "America/New_York"
    # the short side of the same bars: entry 101, exit 103 -> -2 gross, -2.75 net; MAE 104-101, MFE 101-100.5
    ts_ = one_trade(eng.run(b, eng.Signals(arr(5, {0: -1}), max_bars=2)))
    assert ts_.direction == -1 and ts_.entry_price == 101.0 and close(ts_.gross_pts, -2.0) and close(ts_.net_pts, -2.75)
    assert close(ts_.mae_pts, 3.0) and close(ts_.mfe_pts, 0.5)


@test
def a02_stop_entry_fills_at_touch_plus_one_tick_and_at_open_when_gapped():
    base = [("10:00", 100, 100.5, 99.5, 100),         # signal: buy stop 102
            ("10:05", 100, 101.75, 99.75, 101)]       # high 101.75 < 102: no fill
    tail = [("10:15", 101.5, 103, 101, 102.5), ("10:20", 102.5, 102.5, 102.5, 102.5), ("10:25", 102.5, 102.5, 102.5, 102.5)]
    # (a) the bar's high equals the stop price: a stop order fills at the touch, at 102 + 1 tick
    b = B(base + [("10:10", 101, 102, 100.5, 101.5)] + tail)
    S = eng.Signals(long=dict(entry=mask(b.n, 0), order="stop", price=arr(b.n, fill=102.0)), max_bars=2)
    tr = one_trade(eng.run(b, S))
    assert tr.entry_bar == 2 and tr.entry_price == 102.25 and tr.order_type == "stop"
    assert tr.exit_bar == 3 and tr.exit_price == 102.5 and close(tr.gross_pts, 0.25) and close(tr.net_pts, -0.5)
    assert close(tr.slippage_pts, 0.25)
    # entry bar of a stop entry: adverse extreme and close only -> worst 100.5; then bar 3: low 101, high 103
    assert close(tr.mae_pts, 102.25 - 100.5) and close(tr.mfe_pts, 103 - 102.25)
    # (b) the bar opens beyond the stop: filled at the open + 1 tick, not at the stop price
    b = B(base + [("10:10", 103, 104, 102.5, 103.5)] + tail)
    tr = one_trade(eng.run(b, eng.Signals(long=dict(entry=mask(b.n, 0), order="stop", price=arr(b.n, fill=102.0)), max_bars=2)))
    assert tr.entry_bar == 2 and tr.entry_price == 103.25
    # (c) sell stop 98: low touches 98 -> 97.75; opens at 97 -> 96.75
    b = B([("10:00", 100, 100.5, 99.5, 100), ("10:05", 100, 100.25, 98.25, 99), ("10:10", 99, 99.5, 98, 98.5),
           ("10:15", 98.5, 99, 97, 97.5), ("10:20", 97.5, 97.5, 97.5, 97.5), ("10:25", 97.5, 97.5, 97.5, 97.5)])
    tr = one_trade(eng.run(b, eng.Signals(short=dict(entry=mask(b.n, 0), order="stop", price=arr(b.n, fill=98.0)), max_bars=2)))
    assert tr.entry_bar == 2 and tr.entry_price == 97.75 and tr.direction == -1
    assert tr.exit_price == 97.5 and close(tr.gross_pts, 0.25) and close(tr.net_pts, -0.5)
    b = B([("10:00", 100, 100.5, 99.5, 100), ("10:05", 97, 97.5, 96.5, 97.25), ("10:10", 97.25, 97.5, 97, 97.25),
           ("10:15", 97.25, 97.25, 97.25, 97.25), ("10:20", 97.25, 97.25, 97.25, 97.25)])
    tr = one_trade(eng.run(b, eng.Signals(short=dict(entry=mask(b.n, 0), order="stop", price=arr(b.n, fill=98.0)), max_bars=2)))
    assert tr.entry_bar == 1 and tr.entry_price == 96.75


@test
def a03_limit_entry_needs_trade_through_touch_does_not_fill():
    # buy limit 99
    rows = [("10:00", 100, 100.5, 99.5, 100),        # signal
            ("10:05", 100, 100.25, 99, 99.5),        # low == 99: a touch does NOT fill
            ("10:10", 99.5, 99.75, 98.75, 99.25),    # low 98.75 < 99: filled at 99 (opens above the limit)
            ("10:15", 99.25, 99.25, 99.25, 99.25), ("10:20", 99.25, 99.25, 99.25, 99.25)]
    b = B(rows)
    S = lambda: eng.Signals(long=dict(entry=mask(b.n, 0), order="limit", price=arr(b.n, fill=99.0)), max_bars=1)
    tr = one_trade(eng.run(b, S()))
    assert tr.entry_bar == 2 and tr.entry_price == 99.0 and tr.order_type == "limit" and tr.slippage_pts == 0.0
    assert tr.exit_bar == 2 and tr.exit_price == 99.25 and close(tr.net_pts, 0.25 - 0.75)
    # a bar that only touches the limit, on every bar: never filled
    b = B([("10:00", 100, 100.5, 99.5, 100), ("10:05", 100, 100.25, 99, 99.5), ("10:10", 99.5, 99.75, 99, 99.25),
           ("10:15", 99.25, 99.5, 99, 99.25)])
    r = eng.run(b, S())
    assert len(r.trades) == 0 and r.diag["orders"] == 1 and r.diag["fills"] == 0
    # the bar opens below the buy limit: filled at the open (better than the limit)
    b = B([("10:00", 100, 100.5, 99.5, 100), ("10:05", 98.5, 98.75, 98, 98.25), ("10:10", 98.25, 98.25, 98.25, 98.25),
           ("10:15", 98.25, 98.25, 98.25, 98.25)])
    tr = one_trade(eng.run(b, S()))
    assert tr.entry_bar == 1 and tr.entry_price == 98.5 and tr.exit_price == 98.25 and close(tr.net_pts, -0.25 - 0.75)
    # sell limit 101: touch at 101 no fill; 101.25 fills at 101; open 101.5 fills at 101.5
    b = B([("10:00", 100, 100.5, 99.5, 100), ("10:05", 100, 101, 99.75, 100.5), ("10:10", 100.5, 101.25, 100.25, 100.75),
           ("10:15", 100.75, 100.75, 100.75, 100.75), ("10:20", 100.75, 100.75, 100.75, 100.75)])
    Ss = lambda: eng.Signals(short=dict(entry=mask(b.n, 0), order="limit", price=arr(b.n, fill=101.0)), max_bars=1)
    tr = one_trade(eng.run(b, Ss()))
    assert tr.entry_bar == 2 and tr.entry_price == 101.0 and tr.exit_price == 100.75 and close(tr.net_pts, 0.25 - 0.75)
    b = B([("10:00", 100, 100.5, 99.5, 100), ("10:05", 101.5, 102, 101.25, 101.75), ("10:10", 101.75, 101.75, 101.75, 101.75),
           ("10:15", 101.75, 101.75, 101.75, 101.75)])
    tr = one_trade(eng.run(b, Ss()))
    assert tr.entry_bar == 1 and tr.entry_price == 101.5 and close(tr.gross_pts, -0.25)


@test
def a04_protective_stop_at_touch_and_gapped_through():
    head = [("10:00", 100, 100.5, 99.5, 100),         # signal: market long, stop price 98
            ("10:05", 100, 100.5, 99, 99.5)]          # entry 100
    tail = [("10:15", 97, 97, 97, 97), ("10:20", 97, 97, 97, 97)]
    S = lambda b, d=1, stop=98.0: eng.Signals(arr(b.n, {0: d}), stop=arr(b.n, fill=stop))
    # (a) low equals the stop: exit at the stop price less one tick
    b = B(head + [("10:10", 99.5, 99.75, 98, 98.5)] + tail)
    tr = one_trade(eng.run(b, S(b)))
    assert tr.exit_reason == "stop" and tr.exit_bar == 2 and tr.exit_price == 97.75
    assert close(tr.gross_pts, -2.25) and close(tr.net_pts, -3.0) and close(tr.slippage_pts, 0.25)
    assert close(tr.risk_pts, 2.0) and close(tr.r_multiple, -1.5) and tr.stop_price == 98.0
    assert close(tr.mae_pts, 2.0) and close(tr.mfe_pts, 0.5)     # adverse up to the stop price; favourable 100.5
    # (b) the bar opens below the stop: exit at the open less one tick (worse than the stop)
    b = B(head + [("10:10", 97, 97.5, 96, 96.5)] + tail)
    tr = one_trade(eng.run(b, S(b)))
    assert tr.exit_reason == "stop" and tr.exit_price == 96.75 and close(tr.gross_pts, -3.25) and close(tr.net_pts, -4.0)
    assert close(tr.mae_pts, 3.0)
    # (c) a low just above the stop does not exit
    b = B(head + [("10:10", 99.5, 99.75, 98.25, 98.5), ("10:15", 98.5, 98.5, 98.5, 98.5), ("10:20", 98.5, 98.5, 98.5, 98.5)])
    tr = one_trade(eng.run(b, S(b)))
    assert tr.exit_reason == "eod"
    # (d) short: stop 102 touched -> 102.25; gapped (open 103) -> 103.25
    b = B([("10:00", 100, 100.5, 99.5, 100), ("10:05", 100, 101, 99.5, 100.5), ("10:10", 100.5, 102, 100.25, 101.5),
           ("10:15", 103, 103, 103, 103), ("10:20", 103, 103, 103, 103)])
    tr = one_trade(eng.run(b, S(b, -1, 102.0)))
    assert tr.exit_reason == "stop" and tr.exit_price == 102.25 and close(tr.net_pts, -2.25 - 0.75)
    b = B([("10:00", 100, 100.5, 99.5, 100), ("10:05", 100, 101, 99.5, 100.5), ("10:10", 103, 103.5, 102.5, 103),
           ("10:15", 103, 103, 103, 103), ("10:20", 103, 103, 103, 103)])
    tr = one_trade(eng.run(b, S(b, -1, 102.0)))
    assert tr.exit_reason == "stop" and tr.exit_price == 103.25 and close(tr.net_pts, -3.25 - 0.75)


@test
def a05_stop_and_target_in_one_bar_takes_the_stop():
    b = B([("10:00", 100, 100.5, 99.5, 100), ("10:05", 100, 100.5, 99.5, 100),
           ("10:10", 100, 103, 97.5, 101),              # both 98 and 102 are inside this bar
           ("10:15", 101, 101, 101, 101), ("10:20", 101, 101, 101, 101)])
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {0: 1}), stop=arr(b.n, fill=98.0), target=arr(b.n, fill=102.0))))
    assert tr.exit_reason == "stop" and tr.exit_bar == 2 and tr.exit_price == 97.75 and close(tr.net_pts, -3.0)
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {0: -1}), stop=arr(b.n, fill=102.0), target=arr(b.n, fill=98.0))))
    assert tr.exit_reason == "stop" and tr.exit_price == 102.25 and close(tr.net_pts, -3.0)


@test
def a06_target_needs_trade_through_and_is_never_better():
    head = [("10:00", 100, 100.5, 99.5, 100), ("10:05", 100, 100.5, 99.5, 100)]      # long 100, target 102
    S = lambda b, d=1, t=102.0: eng.Signals(arr(b.n, {0: d}), target=arr(b.n, fill=t))
    b = B(head + [("10:10", 100, 102, 99.75, 101.5),        # high == target: not filled
                  ("10:15", 101.5, 102.25, 101, 102),       # through: filled at 102
                  ("10:20", 102, 102, 102, 102), ("10:25", 102, 102, 102, 102)])
    tr = one_trade(eng.run(b, S(b)))
    assert tr.exit_reason == "target" and tr.exit_bar == 3 and tr.exit_price == 102.0
    assert close(tr.gross_pts, 2.0) and close(tr.net_pts, 1.25) and tr.slippage_pts == 0.0 and tr.target_price == 102.0
    assert close(tr.mfe_pts, 2.0)                               # favourable only up to the target
    # the bar gaps far beyond the target: still filled at the target
    b = B(head + [("10:10", 105, 106, 104.5, 105.5), ("10:15", 105.5, 105.5, 105.5, 105.5), ("10:20", 105.5, 105.5, 105.5, 105.5)])
    tr = one_trade(eng.run(b, S(b)))
    assert tr.exit_reason == "target" and tr.exit_price == 102.0 and close(tr.net_pts, 1.25)
    # short, target 98: low == 98 no; 97.75 yes at 98
    b = B(head + [("10:10", 100, 100.25, 98, 98.5), ("10:15", 98.5, 99, 97.75, 98.25), ("10:20", 98.25, 98.25, 98.25, 98.25),
                  ("10:25", 98.25, 98.25, 98.25, 98.25)])
    tr = one_trade(eng.run(b, S(b, -1, 98.0)))
    assert tr.exit_reason == "target" and tr.exit_bar == 3 and tr.exit_price == 98.0 and close(tr.net_pts, 1.25)


@test
def a07_entry_bar_of_stop_entry_stop_counts_target_does_not():
    head = [("10:00", 100, 100.5, 99.5, 100), ("10:05", 100, 101.75, 99.75, 101)]     # buy stop 102, stop 100, target 103
    S = lambda b: eng.Signals(long=dict(entry=mask(b.n, 0), order="stop", price=arr(b.n, fill=102.0)),
                              stop=arr(b.n, fill=100.0), target=arr(b.n, fill=103.0))
    # (a) entry bar reaches the protective stop: stopped in the entry bar (stop-in, stop-out)
    b = B(head + [("10:10", 101, 104, 99.5, 103.5), ("10:15", 103.5, 103.5, 103.5, 103.5), ("10:20", 103.5, 103.5, 103.5, 103.5)])
    tr = one_trade(eng.run(b, S(b)))
    assert tr.entry_bar == 2 and tr.exit_bar == 2 and tr.entry_price == 102.25 and tr.exit_price == 99.75
    assert tr.exit_reason == "stop" and close(tr.gross_pts, -2.5) and close(tr.net_pts, -3.25) and close(tr.slippage_pts, 0.5)
    assert tr.bars_held == 1 and close(tr.risk_pts, 2.25) and close(tr.r_multiple, -3.25 / 2.25)
    # (b) entry bar trades through the target (high 104 > 103) but not the stop: the target does NOT count there
    b = B(head + [("10:10", 101, 104, 100.5, 102.5),
                  ("10:15", 102.5, 102.75, 102, 102.5),           # high 102.75 < 103: still open
                  ("10:20", 102.5, 103.25, 102.25, 103),          # through 103: target
                  ("10:25", 103, 103, 103, 103), ("10:30", 103, 103, 103, 103)])
    tr = one_trade(eng.run(b, S(b)))
    assert tr.entry_bar == 2 and tr.exit_bar == 4 and tr.exit_reason == "target" and tr.exit_price == 103.0
    assert close(tr.gross_pts, 0.75) and close(tr.net_pts, 0.0)
    # (c) a MARKET entry bar is a full bar: the target counts on it
    b = B([("10:00", 100, 100.5, 99.5, 100), ("10:05", 100, 101.5, 99.75, 101), ("10:10", 101, 101, 101, 101),
           ("10:15", 101, 101, 101, 101)])
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {0: 1}), target=arr(b.n, fill=101.0), stop=arr(b.n, fill=99.0))))
    assert tr.entry_bar == 1 and tr.exit_bar == 1 and tr.exit_reason == "target" and close(tr.net_pts, 0.25)
    # (d) entry bar of a LIMIT entry: stop counts, target does not
    b = B([("10:00", 100, 100.5, 99.5, 100),
           ("10:05", 100, 102, 97.9, 101),                   # buy limit 99 filled at 99; low 97.9 <= stop 98 -> out at 97.75
           ("10:10", 101, 101, 101, 101), ("10:15", 101, 101, 101, 101)])
    tr = one_trade(eng.run(b, eng.Signals(long=dict(entry=mask(b.n, 0), order="limit", price=arr(b.n, fill=99.0)),
                                           stop=arr(b.n, fill=98.0), target=arr(b.n, fill=101.5))))
    assert tr.entry_price == 99.0 and tr.exit_bar == 1 and tr.exit_reason == "stop" and tr.exit_price == 97.75
    assert close(tr.net_pts, -1.25 - 0.75)
    b = B([("10:00", 100, 100.5, 99.5, 100),
           ("10:05", 100, 102, 98.5, 101),                   # filled at 99; high 102 > target 101.5 but entry bar: no target
           ("10:10", 101, 101.25, 100.5, 101),               # 101.25 < 101.5
           ("10:15", 101, 101, 101, 101)])
    tr = one_trade(eng.run(b, eng.Signals(long=dict(entry=mask(b.n, 0), order="limit", price=arr(b.n, fill=99.0)),
                                           stop=arr(b.n, fill=98.0), target=arr(b.n, fill=101.5))))
    assert tr.exit_reason == "eod" and tr.exit_bar == 3 and tr.exit_price == 101.0


@test
def a08_stop_on_wrong_side_at_entry_is_hit_at_once():
    b = B([("10:00", 100, 100.5, 99.5, 100), ("10:05", 100, 100.5, 99.75, 100.25), ("10:10", 100.25, 100.25, 100.25, 100.25),
           ("10:15", 100.25, 100.25, 100.25, 100.25)])
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {0: 1}), stop=arr(b.n, fill=101.0))))      # long 100, "stop" at 101
    assert tr.entry_bar == 1 and tr.exit_bar == 1 and tr.exit_reason == "stop" and tr.exit_price == 99.75
    assert close(tr.gross_pts, -0.25) and close(tr.net_pts, -1.0)
    # a stop ENTRY with its protective stop on the wrong side: in at 102 + 1 tick, out one tick beyond the order's
    # fill price 102 -> two ticks and the cost
    b = B([("10:00", 100, 100.5, 99.5, 100), ("10:05", 100, 102.5, 99.75, 102), ("10:10", 102, 102, 102, 102),
           ("10:15", 102, 102, 102, 102)])
    tr = one_trade(eng.run(b, eng.Signals(long=dict(entry=mask(b.n, 0), order="stop", price=arr(b.n, fill=102.0)),
                                           stop=arr(b.n, fill=103.0))))
    assert tr.entry_price == 102.25 and tr.exit_price == 101.75 and tr.exit_bar == 1 and close(tr.net_pts, -0.5 - 0.75)
    assert math.isnan(tr.risk_pts) and math.isnan(tr.r_multiple)          # no positive risk: no R multiple


@test
def a09_partial_exit_and_stop_move():
    rows = [("10:00", 100, 100.5, 99.5, 100),          # signal: market long, stop 96, tp1 104 (half), target 110
            ("10:05", 100, 101, 99.5, 100.5),          # entry 100
            ("10:10", 100.5, 104.5, 99.75, 104),       # trades through 104: half out at 104.  Low 99.75 is below the
                                                       #   new breakeven stop, but the move counts from the NEXT bar
            ("10:15", 104, 104.25, 100, 100.5),        # low 100 reaches the stop at 100: rest out at 99.75
            ("10:20", 100.5, 100.5, 100.5, 100.5), ("10:25", 100.5, 100.5, 100.5, 100.5)]
    b = B(rows)
    kw = dict(stop=arr(b.n, fill=96.0), tp1=arr(b.n, fill=104.0), target=arr(b.n, fill=110.0))
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {0: 1}), **kw)))
    assert tr.exit_bar == 3 and tr.exit_reason == "stop" and tr.exit_price == 99.75
    assert bool(tr.partial_exit) and tr.partial_price == 104.0 and tr.partial_frac == 0.5
    assert close(tr.gross_pts, 0.5 * 4.0 + 0.5 * (-0.25))          # 1.875
    assert close(tr.slippage_pts, 0.125) and close(tr.net_pts, 1.125)
    assert close(tr.risk_pts, 4.0) and close(tr.r_multiple, 1.125 / 4.0) and tr.stop_price == 96.0
    # tp1_stop='keep': the stop stays at 96, bar 3 does not stop it; out at the end of the day at 100.5
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {0: 1}), tp1_stop="keep", **kw)))
    assert tr.exit_reason == "eod" and tr.exit_price == 100.5 and close(tr.gross_pts, 0.5 * 4.0 + 0.5 * 0.5)
    # tp1_stop=1.0: stop to 101; bar 3 opens at 104 and falls to 100: out at 101 - 0.25
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {0: 1}), tp1_stop=1.0, **kw)))
    assert tr.exit_reason == "stop" and tr.exit_price == 100.75 and close(tr.gross_pts, 0.5 * 4.0 + 0.5 * 0.75)
    # tp1_frac=0.25: a quarter at 104, three quarters at 99.75
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {0: 1}), tp1_frac=0.25, **kw)))
    assert close(tr.gross_pts, 0.25 * 4.0 + 0.75 * (-0.25)) and close(tr.slippage_pts, 0.75 * 0.25)
    # a touch of tp1 (high == 104) is not a fill
    rows2 = list(rows)
    rows2[2] = ("10:10", 100.5, 104, 99.75, 103.5)
    rows2[3] = ("10:15", 103.5, 103.75, 100, 100.5)
    b2 = B(rows2)
    tr = one_trade(eng.run(b2, eng.Signals(arr(b2.n, {0: 1}), **kw)))
    assert not bool(tr.partial_exit) and tr.exit_reason == "eod" and tr.partial_frac == 0.0
    # stop and first target in one bar: the stop is taken for the whole position
    rows3 = list(rows)
    rows3[2] = ("10:10", 100.5, 104.5, 95.5, 104)
    b3 = B(rows3)
    tr = one_trade(eng.run(b3, eng.Signals(arr(b3.n, {0: 1}), **kw)))
    assert tr.exit_reason == "stop" and not bool(tr.partial_exit) and tr.exit_price == 95.75 and close(tr.net_pts, -5.0)


@test
def a10_slippage_and_cost_arithmetic():
    # stop-in, stop-out: ideal prices 102 -> 100 = -2; with 2 ticks slippage and 0.75 costs: -3.25
    b = B([("10:00", 100, 100.5, 99.5, 100), ("10:05", 100.5, 102.5, 100.25, 102), ("10:10", 102, 102.25, 99.5, 100),
           ("10:15", 100, 100, 100, 100), ("10:20", 100, 100, 100, 100)])
    tr = one_trade(eng.run(b, eng.Signals(long=dict(entry=mask(b.n, 0), order="stop", price=arr(b.n, fill=102.0)),
                                           stop=arr(b.n, fill=100.0))))
    assert tr.entry_bar == 1 and tr.exit_bar == 2
    assert tr.entry_price == 102.25 and tr.exit_price == 99.75 and close(tr.slippage_pts, 0.5)
    assert close(tr.gross_pts, -2.5) and close(tr.net_pts, -2.0 - 1.25) and tr.cost_pts == 0.75
    # market-in, target-out: 0.75 only
    b = B([("10:00", 100, 100.5, 99.5, 100), ("10:05", 100, 100.5, 99.75, 100.25), ("10:10", 100.25, 103.5, 100, 103),
           ("10:15", 103, 103, 103, 103), ("10:20", 103, 103, 103, 103)])
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {0: 1}), target_pts=3.0)))
    assert tr.entry_price == 100.0 and tr.exit_price == 103.0 and tr.slippage_pts == 0.0 and close(tr.net_pts, 3.0 - 0.75)
    # stop_pts is measured from the actual fill (incl. the entry tick): stop entry at 102.25, stop_pts 2 -> stop 100.25
    b = B([("10:00", 100, 100.5, 99.5, 100), ("10:05", 100.5, 102.5, 100.5, 102), ("10:10", 102, 102.25, 100.25, 100.5),
           ("10:15", 100.5, 100.5, 100.5, 100.5), ("10:20", 100.5, 100.5, 100.5, 100.5)])
    tr = one_trade(eng.run(b, eng.Signals(long=dict(entry=mask(b.n, 0), order="stop", price=arr(b.n, fill=102.0)),
                                           stop_pts=2.0, target_r=2.0)))
    assert tr.stop_price == 100.25 and close(tr.risk_pts, 2.0) and tr.target_price == 106.25
    assert tr.exit_reason == "stop" and tr.exit_price == 100.0 and close(tr.net_pts, -2.25 - 0.75)
    assert eng.TICK == 0.25 and eng.SLIPPAGE == 0.25 and eng.COST_RT == 0.75


LATE = [("15:40", 100, 100.5, 99.5, 100), ("15:45", 100, 100.5, 99.5, 100), ("15:50", 100, 100.5, 99.5, 100.25),
        ("15:55", 101, 101.5, 100.5, 101), ("16:00", 102, 102.5, 101.5, 102), ("16:05", 103, 103.5, 102.5, 103.25),
        ("16:10", 104, 104.5, 103.5, 104)]


@test
def a11_last_entry_time():
    b = B(LATE)
    # market signal on the 15:50 bar -> filled at the 15:55 open (a bar that opens at 15:55 is allowed)
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {2: 1}))))
    assert tr.entry_bar == 3 and tr.entry_price == 101.0 and et_str(tr.entry_time) == "2021-06-15 15:55"
    # market signal on the 15:55 bar -> the next bar opens at 16:00, after the last entry time: dropped, not carried
    r = eng.run(b, eng.Signals(arr(b.n, {3: 1})))
    assert len(r.trades) == 0 and r.diag["orders"] == 1
    # stop order: may fill in the bar that ENDS at 15:55 (the 15:50 bar) ...
    r = eng.run(b, eng.Signals(long=dict(entry=mask(b.n, 1), order="stop", price=arr(b.n, fill=100.5))))
    tr = one_trade(r)
    assert tr.entry_bar == 2 and tr.entry_price == 100.75
    # ... but not in the 15:55 bar (it ends at 16:00), although its range holds the price
    r = eng.run(b, eng.Signals(long=dict(entry=mask(b.n, 1), order="stop", price=arr(b.n, fill=101.25))))
    assert len(r.trades) == 0
    # same for a limit order (sell limit 101.25 would trade through in the 15:55 bar only)
    r = eng.run(b, eng.Signals(short=dict(entry=mask(b.n, 1), order="limit", price=arr(b.n, fill=101.25))))
    assert len(r.trades) == 0
    # an explicit earlier last_entry: 15:45 -> the market signal on the 15:45 bar (fills 15:50) is refused
    assert len(eng.run(b, eng.Signals(arr(b.n, {1: 1}), last_entry="15:45")).trades) == 0
    assert len(eng.run(b, eng.Signals(arr(b.n, {0: 1}), last_entry="15:45")).trades) == 1
    # first_entry: an entry needs a bar that opens at or after it
    assert len(eng.run(b, eng.Signals(arr(b.n, {0: 1}), first_entry="15:50")).trades) == 0
    assert len(eng.run(b, eng.Signals(arr(b.n, {1: 1}), first_entry="15:50")).trades) == 1


@test
def a12_forced_flat_at_last_bar_ending_by_1610():
    b = B(LATE + [("2021-06-15 18:00", 105, 105.5, 104.5, 105), ("2021-06-15 18:05", 105, 105.5, 104.5, 105)])
    r = eng.run(b, eng.Signals(arr(b.n, {2: 1})))
    tr = one_trade(r)
    # in at 15:55 (101); out at the close of the 16:05 bar (it ends at 16:10): 103.25.  The 16:10 bar is not used.
    assert tr.exit_reason == "eod" and tr.exit_bar == 5 and tr.exit_price == 103.25
    assert et_str(tr.exit_time) == "2021-06-15 16:10" and close(tr.net_pts, 2.25 - 0.75) and tr.slippage_pts == 0.0
    assert close(tr.mfe_pts, 2.5)                              # 103.5 - 101: nothing of the 16:10 bar (high 104.5)
    # a pending stop order is dead after 16:10: the 16:10 bar trades through 104.25 but nothing fills, nor next day
    r = eng.run(b, eng.Signals(long=dict(entry=mask(b.n, 0), order="stop", price=arr(b.n, fill=104.25)), last_entry=None))
    assert len(r.trades) == 0
    # with last_entry=None a market order may still enter on the 16:05 bar, and is flat at its close
    r = eng.run(b, eng.Signals(arr(b.n, {4: 1}), last_entry=None))
    tr = one_trade(r)
    assert tr.entry_bar == 5 and tr.exit_bar == 5 and tr.entry_price == 103.0 and tr.exit_price == 103.25
    # ... but never on the 16:10 bar
    assert len(eng.run(b, eng.Signals(arr(b.n, {5: 1}), last_entry=None)).trades) == 0
    # 1-minute bars: the 16:09 bar is the last one that ends by 16:10
    rows = [(f"16:{m:02d}", 100 + m, 100.5 + m, 99.5 + m, 100.25 + m) for m in range(0, 15)]
    b1 = B([("15:58", 99, 99.5, 98.5, 99), ("15:59", 99, 99.5, 98.5, 99)] + rows, res=1)
    tr = one_trade(eng.run(b1, eng.Signals(arr(b1.n, {0: 1}), last_entry=None)))
    assert et_str(tr.exit_time) == "2021-06-15 16:10" and tr.exit_price == 109.25 and tr.exit_reason == "eod"
    # 15-minute bars: the 15:45 bar (ends 16:00) is the last one that ends by 16:10; the 16:00 bar ends at 16:15
    b15 = B([("15:15", 100, 100.5, 99.5, 100), ("15:30", 100, 100.5, 99.5, 100), ("15:45", 101, 101.5, 100.5, 101.25),
             ("16:00", 102, 102.5, 101.5, 102)], res=15)
    tr = one_trade(eng.run(b15, eng.Signals(arr(b15.n, {0: 1}))))
    assert tr.entry_bar == 1 and tr.exit_bar == 2 and tr.exit_price == 101.25 and et_str(tr.exit_time) == "2021-06-15 16:00"
    assert int(b15.tmin_end[3]) == 1335 and int(b15.end_mod[3]) == 16 * 60 + 15      # the 16:00 bar is capped at 16:15
    # a day whose data stops early: flat at its last bar, nothing is carried into the evening
    bh = B([("12:50", 100, 100.5, 99.5, 100), ("12:55", 100, 100.5, 99.5, 100.25), ("13:00", 100.25, 101, 100, 100.75),
            ("2021-06-15 18:00", 105, 105.5, 104.5, 105), ("2021-06-15 18:05", 105, 105.5, 104.5, 105)])
    tr = one_trade(eng.run(bh, eng.Signals(arr(bh.n, {0: 1}))))
    assert tr.exit_reason == "eod" and tr.exit_bar == 2 and tr.exit_price == 100.75


@test
def a13_no_bar_after_1615():
    ok = [("16:10", 100, 100.5, 99.5, 100)]
    for bad in ("16:15", "16:20", "17:00", "17:55"):
        try:
            B(ok + [(bad, 100, 100.5, 99.5, 100)])
        except ValueError:
            continue
        raise AssertionError(f"a bar that opens at {bad} ET was accepted")
    B(ok + [("18:00", 100, 100.5, 99.5, 100)])                  # 18:00 is the next trading day: fine
    # resample_1m drops the minutes 16:15 .. 17:59 before bucketing
    mins = ["16:13", "16:14", "16:15", "16:16", "17:30", "17:59", "18:00", "18:01"]
    t = [ts("2021-06-15 " + m) for m in mins]
    px = [100, 101, 500, 600, 700, 800, 102, 103]
    r = eng.resample_1m(t, px, px, px, px, 5)
    assert list(r["t"]) == [ts("2021-06-15 16:10"), ts("2021-06-15 18:00")]
    assert list(r["h"]) == [101, 103] and list(r["c"]) == [101, 103] and list(r["tmin_end"]) == [1335, 5]
    # the real bars at 1, 5 and 15 minutes: nothing opens in [16:15, 18:00), nothing ends after 16:15
    for res in (5, 15):
        bb = eng.load_bars(res)
        assert not ((bb.mod >= 16 * 60 + 15) & (bb.mod < 18 * 60)).any()
        assert int(bb.tmin_end.max()) <= 1335 and int(bb.tmin.max()) < 1335
    # the 1-minute file itself has such minutes in the early years; they are in no 5-minute bar of the engine
    z = raw_1m()
    t1 = z["t"]
    i0 = int(np.searchsorted(t1, ts("2016-06-15 16:00")))
    i1 = int(np.searchsorted(t1, ts("2016-06-15 18:00")))
    late = t1[i0:i1][t1[i0:i1] >= ts("2016-06-15 16:15")]
    assert len(late) > 10, "expected 1-minute bars after 16:15 ET on 2016-06-15 in the raw file"
    b5 = eng.load_bars(5)
    k = int(np.searchsorted(b5.t, ts("2016-06-15 16:10")))
    assert b5.t[k] == ts("2016-06-15 16:10") and b5.t[k + 1] == ts("2016-06-15 18:00")
    m = (t1 >= ts("2016-06-15 16:10")) & (t1 < ts("2016-06-15 16:15"))
    assert b5.h[k] == z["h"][m].max() and b5.l[k] == z["l"][m].min() and b5.c[k] == z["c"][m][-1] and b5.o[k] == z["o"][m][0]


@test
def a14_trading_day_ids_midnight_sunday_open_and_dst():
    D = lambda s: int(np.datetime64(s, "D").astype("int64"))
    # (a) around midnight and the 18:00 roll, an ordinary week (EDT = UTC-4)
    t = [utc(2021, 6, 17, 20, 10),      # Thu 16:10 ET  -> trading day Thu 06-17
         utc(2021, 6, 17, 22, 0),       # Thu 18:00 ET  -> Fri 06-18, tmin 0
         utc(2021, 6, 18, 3, 55),       # Thu 23:55 ET  -> Fri 06-18
         utc(2021, 6, 18, 4, 0),        # Fri 00:00 ET  -> Fri 06-18, tmin 360
         utc(2021, 6, 18, 13, 30),      # Fri 09:30 ET  -> Fri, tmin 930, regular session
         utc(2021, 6, 18, 20, 10),      # Fri 16:10 ET  -> Fri
         utc(2021, 6, 20, 22, 0),       # Sun 18:00 ET  -> Mon 06-21
         utc(2021, 6, 21, 13, 30)]      # Mon 09:30 ET  -> Mon
    b = eng.Bars(t, [1.0] * 8, [1.0] * 8, [1.0] * 8, [1.0] * 8, 5)
    assert list(b.tday_id) == [D("2021-06-17"), D("2021-06-18"), D("2021-06-18"), D("2021-06-18"), D("2021-06-18"),
                               D("2021-06-18"), D("2021-06-21"), D("2021-06-21")]
    assert list(b.tmin) == [1330, 0, 355, 360, 930, 1330, 0, 930]
    assert list(b.mod) == [970, 1080, 1435, 0, 570, 970, 1080, 570]
    assert list(b.tday_wd) == [3, 4, 4, 4, 4, 4, 0, 0] and list(b.wd) == [3, 3, 3, 4, 4, 4, 6, 0]
    assert [str(x) for x in b.date] == ["2021-06-17", "2021-06-17", "2021-06-17", "2021-06-18", "2021-06-18", "2021-06-18",
                                       "2021-06-20", "2021-06-21"]
    assert list(b.rth) == [False, False, False, False, True, False, False, True]
    assert list(b.day_idx) == [0, 1, 1, 1, 1, 1, 2, 2] and len(b.days) == 3
    assert list(b.tmin_end) == [1335, 5, 360, 365, 935, 1335, 5, 935]
    # (b) spring forward, 2021-03-14: Friday is EST (UTC-5), from Sunday evening EDT (UTC-4)
    t = [utc(2021, 3, 12, 14, 30),      # Fri 09:30 EST
         utc(2021, 3, 12, 21, 10),      # Fri 16:10 EST
         utc(2021, 3, 14, 22, 0),       # Sun 18:00 EDT -> Mon 03-15
         utc(2021, 3, 15, 4, 0),        # Mon 00:00 EDT
         utc(2021, 3, 15, 13, 30),      # Mon 09:30 EDT (an engine on fixed UTC-5 would call this 08:30)
         utc(2021, 3, 15, 19, 55),      # Mon 15:55 EDT: last regular-session 5-minute bar
         utc(2021, 3, 15, 20, 10)]      # Mon 16:10 EDT
    b = eng.Bars(t, [1.0] * 7, [1.0] * 7, [1.0] * 7, [1.0] * 7, 5)
    assert list(b.mod) == [570, 970, 1080, 0, 570, 955, 970]
    assert list(b.tday_id) == [D("2021-03-12")] * 2 + [D("2021-03-15")] * 5
    assert list(b.rth) == [True, False, False, False, True, True, False] and list(b.tmin) == [930, 1330, 0, 360, 930, 1315, 1330]
    # (c) fall back, 2021-11-07: Friday is EDT (UTC-4), from Sunday evening EST (UTC-5)
    t = [utc(2021, 11, 5, 13, 30),      # Fri 09:30 EDT
         utc(2021, 11, 5, 20, 10),      # Fri 16:10 EDT
         utc(2021, 11, 7, 23, 0),       # Sun 18:00 EST -> Mon 11-08
         utc(2021, 11, 8, 5, 0),        # Mon 00:00 EST
         utc(2021, 11, 8, 14, 30),      # Mon 09:30 EST
         utc(2021, 11, 8, 21, 10)]      # Mon 16:10 EST
    b = eng.Bars(t, [1.0] * 6, [1.0] * 6, [1.0] * 6, [1.0] * 6, 5)
    assert list(b.mod) == [570, 970, 1080, 0, 570, 970]
    assert list(b.tday_id) == [D("2021-11-05")] * 2 + [D("2021-11-08")] * 4
    assert list(b.rth) == [True, False, False, False, True, False]
    assert eng.tmin_of("18:00") == 0 and eng.tmin_of("00:00") == 360 and eng.tmin_of("09:30") == 930
    assert eng.tmin_of("16:00") == 1320 and eng.tmin_of("16:10") == 1330 and eng.tmin_of("16:15") == 1335
    # (d) the session rules follow the clock through the change: last entry 15:55 EDT on the Monday after the change
    rows = [("2021-03-15 15:45", 100, 100.5, 99.5, 100), ("2021-03-15 15:50", 100, 100.5, 99.5, 100),
            ("2021-03-15 15:55", 101, 101.5, 100.5, 101), ("2021-03-15 16:00", 102, 102.5, 101.5, 102),
            ("2021-03-15 16:05", 103, 103.5, 102.5, 103.25), ("2021-03-15 16:10", 104, 104.5, 103.5, 104)]
    bb = B(rows)
    assert bb.t[2] == utc(2021, 3, 15, 19, 55)
    tr = one_trade(eng.run(bb, eng.Signals(arr(bb.n, {1: 1}))))
    assert tr.entry_bar == 2 and tr.exit_bar == 4 and tr.exit_reason == "eod" and str(tr.exit_time)[:25] == "2021-03-15 16:10:00-04:00"
    assert len(eng.run(bb, eng.Signals(arr(bb.n, {2: 1}))).trades) == 0


@test
def a15_real_data_time_fields_against_zoneinfo():
    b = eng.load_bars(5)
    rng = np.random.default_rng(1)
    idx = set(int(x) for x in rng.integers(0, b.n, 6000))
    et = b.et
    for y in (2011, 2016, 2019, 2021, 2025):          # every bar of the weeks around both DST changes (US and EU dates)
        m = (et.year == y) & (((et.month == 3) & (et.day >= 6) & (et.day <= 16)) | ((et.month == 11) & (et.day <= 9))
                              | ((et.month == 10) & (et.day >= 24)) | ((et.month == 3) & (et.day >= 24)))
        idx |= set(np.flatnonzero(m).tolist())
    bad = 0
    for i in sorted(idx):
        d = datetime.fromtimestamp(int(b.t[i]), tz=timezone.utc).astimezone(NYZ)
        mod = d.hour * 60 + d.minute
        tday = d.date().toordinal() - 719163 + (1 if mod >= 1080 else 0)
        bad += not (b.mod[i] == mod and b.tday_id[i] == tday and b.tmin[i] == (mod - 1080) % 1440
                    and b.wd[i] == d.weekday() and str(b.date[i]) == d.date().isoformat()
                    and b.tday_wd[i] == (tday + 3) % 7 and bool(b.rth[i]) == (570 <= mod and mod + 5 <= 960)
                    and b.tmin_end[i] == min((mod - 1080) % 1440 + 5, 1335))
    assert bad == 0, f"{bad} of {len(idx)} bars have wrong New York time fields"
    # no trading day falls on a weekend; Sunday bars all belong to Monday and open at 18:00 or later
    assert int(b.tday_wd.max()) <= 4
    sun = b.wd == 6
    assert sun.any() and (b.mod[sun] >= 1080).all() and (b.tday_wd[sun] == 0).all()
    # the regular session opens at 09:30 New York time in every year, also in the weeks in which the US and Europe are
    # on different daylight-saving rules (the source changed its clock convention; an hour's error would show here):
    # the 09:30 bar is about twice as active as the 09:25 bar, the 10:30 bar is no more active than the 10:25 bar
    rng_ = b.h - b.l
    import calendar as _cal
    import datetime as _dt

    def nth_sunday(y, mth, k):
        d = _dt.date(y, mth, 1)
        d += _dt.timedelta(days=(6 - d.weekday()) % 7)
        return d + _dt.timedelta(days=7 * (k - 1))

    def last_sunday(y, mth):
        d = _dt.date(y, mth, _cal.monthrange(y, mth)[1])
        return d - _dt.timedelta(days=(d.weekday() + 1) % 7)

    checked = 0
    for y in range(2011, 2027):
        for a, e in ((nth_sunday(y, 3, 2), last_sunday(y, 3)), (last_sunday(y, 10), nth_sunday(y, 11, 1))):
            m = (b.date >= np.datetime64(a)) & (b.date < np.datetime64(e)) & ~b.incomplete
            mean = lambda mod: float(rng_[m & (b.mod == mod)].mean()) if (m & (b.mod == mod)).any() else None
            v = [mean(k) for k in (565, 570, 625, 630)]
            if None in v:
                continue                                   # spring 2023: source gaps
            j0930, j1030 = v[1] / v[0], v[3] / v[2]
            assert j0930 > 1.5 and j0930 > j1030, f"{a}..{e}: jump at 09:30 {j0930:.2f}, at 10:30 {j1030:.2f}"
            checked += 1
    assert checked >= 30


@test
def a16_incomplete_day_exclusion():
    rows = [("2021-06-14 18:00", 100, 100.5, 99.5, 100), ("2021-06-14 18:05", 100, 100.5, 99.5, 100),      # evening of Tue
            ("2021-06-15 10:00", 100, 100.5, 99.5, 100), ("2021-06-15 10:05", 101, 101.5, 100.5, 101),
            ("2021-06-15 10:10", 101, 101.5, 100.5, 101),
            ("2021-06-15 18:00", 102, 102.5, 101.5, 102), ("2021-06-15 18:05", 102, 102.5, 101.5, 102),      # evening of Wed
            ("2021-06-16 10:00", 102, 102.5, 101.5, 102), ("2021-06-16 10:05", 103, 103.5, 102.5, 103),
            ("2021-06-16 10:10", 103, 103.5, 102.5, 103)]
    n = len(rows)
    sig = arr(n, {0: 1, 2: 1, 5: 1, 7: 1})
    # only one flag set, on a regular-session bar of Tuesday: the WHOLE trading day (also its evening) is blocked
    inc = np.zeros(n, dtype=bool)
    inc[3] = True
    b = B(rows, incomplete=inc)
    assert list(b.incomplete) == [True] * 5 + [False] * 5 and list(b.days["complete"]) == [False, True]
    r = eng.run(b, eng.Signals(sig, max_bars=1))
    assert list(r.trades.entry_bar) == [6, 8], list(r.trades.entry_bar)
    # the same through 1-minute counts: 369 bars is incomplete, 370 is complete
    D = lambda s: int(np.datetime64(s, "D").astype("int64"))
    for cnt, expect in ((369, [6, 8]), (370, [1, 3, 6, 8])):
        b = B(rows, rth_counts=(np.array([D("2021-06-15"), D("2021-06-16")]), np.array([cnt, 390])))
        assert list(b.days["n_rth_1m"]) == [cnt, 390]
        r = eng.run(b, eng.Signals(sig, max_bars=1))
        assert list(r.trades.entry_bar) == expect, (cnt, list(r.trades.entry_bar))
    # a day that is missing from the counts has no regular session at all: incomplete
    b = B(rows, rth_counts=(np.array([D("2021-06-16")]), np.array([390])))
    assert list(b.days["complete"]) == [False, True]
    # also in multi-day mode
    b = B(rows, incomplete=inc)
    r = eng.run(b, eng.Signals(sig, max_bars=1, allow_multi_day=True, last_entry=None))
    assert list(r.trades.entry_bar) == [6, 8]
    # stop and limit entries are blocked too
    r = eng.run(b, eng.Signals(long=dict(entry=mask(n, 2), order="stop", price=arr(n, fill=101.0)), max_bars=1))
    assert len(r.trades) == 0
    # rth_counts(): 09:30 .. 15:59 New York time per date
    t1 = [ts("2021-06-15 09:29"), ts("2021-06-15 09:30"), ts("2021-06-15 12:00"), ts("2021-06-15 15:59"),
          ts("2021-06-15 16:00"), ts("2021-06-15 18:30"), ts("2021-11-08 09:30"), ts("2021-11-08 15:59")]
    ids, cnt = eng.rth_counts(t1)
    assert list(ids) == [D("2021-06-15"), D("2021-11-08")] and list(cnt) == [3, 2]


@test
def a17_incomplete_days_in_the_real_data():
    complete = set(complete_days_1m())
    b = eng.load_bars(5)
    d = b.days
    got = set(d["date"].dt.strftime("%Y-%m-%d")[d["complete"]])
    assert got == complete, (len(got), len(complete))
    assert eng.MIN_RTH_1M_BARS == 370 and len(complete) == 3844
    # dense signals: no trade is ever entered on an incomplete trading day (evening session included)
    rng = np.random.default_rng(3)
    r = eng.run(b, eng.Signals(np.where(rng.random(b.n) < 0.2, 1, 0), max_bars=1, last_entry=None))
    days = set(r.trades.entry_day.dt.strftime("%Y-%m-%d"))
    assert days <= complete and len(days) > 3800
    assert not b.incomplete[r.trades.entry_bar.to_numpy()].any()


@test
def a18_max_trades_per_day():
    rows = []
    for day, base in (("2021-06-15", 100), ("2021-06-16", 200)):
        for k in range(8):
            rows.append((f"{day} 10:{5 * k:02d}", base, base + 1, base - 1, base))
    rows.insert(8, ("2021-06-15 18:00", 150, 151, 149, 150))          # evening: already Wednesday's trading day
    rows.insert(9, ("2021-06-15 18:05", 150, 151, 149, 150))
    b = B(rows)
    sig = arr(b.n, {0: 1, 2: 1, 4: 1, 6: 1, 8: 1, 10: 1, 12: 1, 14: 1})
    r = eng.run(b, eng.Signals(sig, max_bars=1, max_trades_per_day=2))
    # Tuesday: entries at bars 1 and 3 only.  Wednesday (starts with the evening bars 8, 9): entries at bars 9 and 11.
    assert list(r.trades.entry_bar) == [1, 3, 9, 11], list(r.trades.entry_bar)
    r = eng.run(b, eng.Signals(sig, max_bars=1, max_trades_per_day=1))
    assert list(r.trades.entry_bar) == [1, 9]
    r = eng.run(b, eng.Signals(sig, max_bars=1))
    assert list(r.trades.entry_bar) == [1, 3, 5, 7, 9, 11, 13, 15]
    # a stop order that is still waiting when the cap is reached does not fill either
    S = eng.Signals(long=dict(entry=mask(b.n, 0, 1), order=np.array([eng.MARKET, eng.STOP] + [0] * (b.n - 2)),
                              price=arr(b.n, fill=100.5)), max_bars=1, max_trades_per_day=1)
    assert list(eng.run(b, S).trades.entry_bar) == [1]


@test
def a19_split_boundary_is_one_fixed_constant():
    assert eng.SPLIT_DATE == "2020-03-18" and eng.IS_FRACTION == 0.60
    rows = [("2020-03-17 15:00", 100, 101, 99, 100), ("2020-03-17 15:05", 100, 101, 99, 100),      # entry Tue 03-17: IS
            ("2020-03-17 15:10", 100, 101, 99, 100),
            ("2020-03-17 16:10", 100, 101, 99, 100),                                                    # signal bar ends 16:15
            ("2020-03-17 18:00", 100, 101, 99, 100), ("2020-03-17 18:05", 100, 101, 99, 100),      # Tue evening = Wed 03-18: OOS
            ("2020-03-18 10:00", 100, 101, 99, 100), ("2020-03-18 10:05", 100, 101, 99, 100),
            ("2020-03-18 10:10", 100, 101, 99, 100)]
    b = B(rows)
    assert list(b.days["oos"]) == [False, True]
    r = eng.run(b, eng.Signals(arr(b.n, {0: 1, 3: 1, 6: 1}), max_bars=1))
    tr = r.trades
    assert list(tr.entry_bar) == [1, 4, 7]
    assert list(tr.split) == ["IS", "OOS", "OOS"], list(tr.split)
    assert [str(x)[:10] for x in tr.entry_day] == ["2020-03-17", "2020-03-18", "2020-03-18"]
    assert str(tr.entry_time.iloc[1])[:16] == "2020-03-17 18:00"          # calendar day 03-17, trading day 03-18
    st = eng.stats(tr)
    assert st["split_date"] == "2020-03-18" and st["IS"]["trades"] == 1 and st["OOS"]["trades"] == 2 and st["ALL"]["trades"] == 3
    # recompute the split from the 1-minute file without the engine's helpers
    comp = complete_days_1m()
    n_is = int(len(comp) * 0.60)
    assert len(comp) == eng.N_COMPLETE_DAYS == 3844 and n_is == eng.N_IS_DAYS == 2306 and len(comp) - n_is == eng.N_OOS_DAYS
    assert comp[n_is] == eng.SPLIT_DATE and comp[0] == eng.DATA_FIRST_DAY and comp[-1] == eng.DATA_LAST_DAY
    assert comp[n_is - 1] == "2020-03-17"
    sp = eng.compute_split()
    assert sp["split_date"] == eng.SPLIT_DATE and sp["n_is_days"] == n_is and sp["last_is_day"] == "2020-03-17"
    # the real bars carry the same boundary
    bb = eng.load_bars(5)
    d = bb.days
    assert str(d["date"][d["oos"]].iloc[0])[:10] == "2020-03-18" and str(d["date"][~d["oos"]].iloc[-1])[:10] == "2020-03-17"
    assert int((d["complete"] & ~d["oos"]).sum()) == 2306 and int((d["complete"] & d["oos"]).sum()) == 1538
    # the source holds no second date literal for the split: every use goes through SPLIT_DATE
    with open(eng.__file__) as fh:
        src = fh.read()
    assert src.count('"2020-03-18"') == 1 and src.count("2020-03-1") == 1
    assert src.count("SPLIT_DATE") >= 6


@test
def a20_multi_day_switch():
    rows = [("2021-06-15 15:00", 100, 100.5, 99.5, 100),        # signal: market long, stop 97
            ("2021-06-15 15:05", 100, 101, 99.5, 100.5),        # entry 100
            ("2021-06-15 16:05", 101, 101.5, 100.5, 101.25),    # last bar ending by 16:10
            ("2021-06-15 16:10", 101.25, 102, 101, 101.5),
            ("2021-06-15 18:00", 96, 96.5, 95, 95.5),           # next trading day opens below the stop
            ("2021-06-15 18:05", 95.5, 96, 95, 95.5),
            ("2021-06-16 10:00", 95.5, 96, 95, 95.5)]
    b = B(rows)
    S = lambda **kw: eng.Signals(arr(b.n, {0: 1}), stop=arr(b.n, fill=97.0), **kw)
    r = eng.run(b, S())
    tr = one_trade(r)
    assert r.tradeify_usable is True and tr.exit_reason == "eod" and tr.exit_bar == 2 and tr.exit_price == 101.25
    assert close(tr.net_pts, 1.25 - 0.75)
    r = eng.run(b, S(allow_multi_day=True))
    tr = one_trade(r)
    # held across the end of the day; the stop is checked against the next bar's open: 96 - 0.25
    assert r.tradeify_usable is False and tr.exit_reason == "stop" and tr.exit_bar == 4 and tr.exit_price == 95.75
    assert close(tr.gross_pts, -4.25) and close(tr.net_pts, -5.0) and tr.bars_held == 4
    assert str(tr.entry_day)[:10] == "2021-06-15"
    # without a stop the position runs to the end of the data
    r = eng.run(b, eng.Signals(arr(b.n, {0: 1}), allow_multi_day=True))
    tr = one_trade(r)
    assert tr.exit_reason == "end_of_data" and tr.exit_bar == 6 and tr.exit_price == 95.5 and close(tr.net_pts, -4.5 - 0.75)
    # multi-day: a stop order with expiry_bars may wait across days; without it, it is bound to its day
    S2 = lambda **kw: eng.Signals(long=dict(entry=mask(b.n, 1), order="stop", price=arr(b.n, fill=95.75)),
                                  allow_multi_day=True, last_entry=None, **kw)
    assert len(eng.run(b, S2()).trades) == 0 or eng.run(b, S2()).trades.entry_bar.iloc[0] <= 3
    tr = one_trade(eng.run(b, S2(expiry_bars=10)))
    assert tr.entry_bar in (2, 3, 4)
    # intraday: a market signal on the last bar of a day that ends early is dropped; on the bar ending 16:15 it is
    # an order for the next trading day (18:00 open)
    r = eng.run(b, eng.Signals(arr(b.n, {3: 1}), max_bars=1))
    tr = one_trade(r)
    assert tr.entry_bar == 4 and tr.entry_price == 96.0 and str(tr.entry_day)[:10] == "2021-06-16"
    r = eng.run(b, eng.Signals(arr(b.n, {5: 1}), max_bars=1))
    assert len(r.trades) == 1                       # bars 5 and 6 are the same trading day (Wed)
    half = B([("2021-06-15 12:55", 100, 100.5, 99.5, 100), ("2021-06-15 13:00", 100, 100.5, 99.5, 100),
              ("2021-06-15 18:00", 101, 101.5, 100.5, 101), ("2021-06-15 18:05", 101, 101.5, 100.5, 101)])
    r = eng.run(half, eng.Signals(arr(half.n, {1: 1}), max_bars=1))
    assert len(r.trades) == 0 and r.diag["dropped"] == 1
    r = eng.run(half, eng.Signals(arr(half.n, {1: 1}), max_bars=1, allow_multi_day=True))
    assert len(r.trades) == 1 and r.trades.entry_bar.iloc[0] == 2


@test
def a21_time_exit_bars_exit_and_expiry():
    rows = [(f"{h:02d}:{m:02d}", 100 + k, 100.5 + k, 99.5 + k, 100.25 + k)
            for k, (h, m) in enumerate([(14, 40), (14, 45), (14, 50), (14, 55), (15, 0), (15, 5), (15, 10)])]
    b = B(rows)
    # exit_time 15:00 -> the close of the bar that ENDS at 15:00 (the 14:55 bar, index 3): 103.25
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {0: 1}), exit_time="15:00")))
    assert tr.entry_bar == 1 and tr.entry_price == 101.0 and tr.exit_bar == 3 and tr.exit_price == 103.25
    assert tr.exit_reason == "time" and et_str(tr.exit_time) == "2021-06-15 15:00" and tr.minutes_held == 15.0 and tr.bars_held == 3
    # a trade entered after the time-exit bar runs to the end of the day
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {3: 1}), exit_time="15:00")))
    assert tr.entry_bar == 4 and tr.exit_reason == "eod" and tr.exit_bar == 6
    # max_bars=3: the entry bar is bar 1 -> closes at the close of the third bar held
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {0: 1}), max_bars=3)))
    assert tr.exit_bar == 3 and tr.exit_reason == "bars" and tr.bars_held == 3
    # expiry_bars=2: a stop order from bar 0 may fill in bars 1 and 2 only.  104.5 first trades in bar 4 -> never
    S = lambda p, **kw: eng.Signals(long=dict(entry=mask(b.n, 0), order="stop", price=arr(b.n, fill=p)), max_bars=1, **kw)
    assert len(eng.run(b, S(104.5, expiry_bars=2)).trades) == 0
    assert one_trade(eng.run(b, S(104.5, expiry_bars=4))).entry_bar == 4
    assert one_trade(eng.run(b, S(102.5, expiry_bars=2))).entry_bar == 2
    assert one_trade(eng.run(b, S(104.5))).entry_bar == 4                          # no expiry: works all day
    # expiry_time 14:55: only bars that end by 14:55 (bars 1, 2)
    assert len(eng.run(b, S(103.5, expiry_time="14:55")).trades) == 0             # 103.5 first trades in bar 3
    assert one_trade(eng.run(b, S(102.5, expiry_time="14:55"))).entry_bar == 2
    # a market order is for the next bar only: refused there (first_entry), it is not carried forward
    assert len(eng.run(b, eng.Signals(arr(b.n, {0: 1}), first_entry="14:50")).trades) == 0


@test
def a22_exit_signal_and_reverse_at_next_open():
    rows = [("10:00", 100, 100.5, 99.5, 100), ("10:05", 101, 102, 100.5, 101.5), ("10:10", 102, 103, 101.5, 102.5),
            ("10:15", 103, 104, 102.5, 103.5), ("10:20", 104, 105, 103.5, 104.5), ("10:25", 105, 105, 105, 105),
            ("10:30", 105, 105, 105, 105)]
    b = B(rows)
    # long from bar 1 (101); exit signal at the close of bar 2 -> out at the open of bar 3 = 103
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {0: 1}), exit_long=mask(b.n, 2))))
    assert tr.exit_bar == 3 and tr.exit_price == 103.0 and tr.exit_reason == "signal" and close(tr.net_pts, 2.0 - 0.75)
    assert et_str(tr.exit_time) == "2021-06-15 10:15" and tr.bars_held == 2 and tr.minutes_held == 10.0
    assert close(tr.mfe_pts, 2.0) and close(tr.mae_pts, 0.5)        # highs 102, 103 and the exit open 103; low 100.5
    # exit and opposite entry on the same bar: reverse at the same open, two trades, each pays 0.75
    r = eng.run(b, eng.Signals(arr(b.n, {0: 1, 2: -1}), exit_long=mask(b.n, 2), max_bars=10))
    assert list(r.trades.direction) == [1, -1] and list(r.trades.entry_bar) == [1, 3] and list(r.trades.exit_bar)[0] == 3
    assert r.trades.entry_price.iloc[1] == 103.0 and r.trades.exit_price.iloc[0] == 103.0
    assert close(r.trades.net_pts.iloc[0], 1.25) and r.trades.exit_reason.iloc[1] == "eod"
    assert close(r.trades.net_pts.iloc[1], (103.0 - 105.0) - 0.75)
    # an entry signal while a position is open (and no exit signal) is ignored
    r = eng.run(b, eng.Signals(arr(b.n, {0: 1, 2: -1})))
    assert len(r.trades) == 1 and r.trades.exit_reason.iloc[0] == "eod"


@test
def a23_breakeven_and_trailing_count_from_the_next_bar():
    rows = [("10:00", 100, 100.5, 99.5, 100),
            ("10:05", 100, 100.75, 99.75, 100.5),       # entry 100, stop 97
            ("10:10", 100.5, 102, 99.9, 101),           # best 102 >= +2: stop -> 100 from the next bar (low 99.9 is safe)
            ("10:15", 101, 101.5, 100, 100.5),          # low 100 reaches the breakeven stop: out at 99.75
            ("10:20", 100.5, 100.5, 100.5, 100.5), ("10:25", 100.5, 100.5, 100.5, 100.5)]
    b = B(rows)
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {0: 1}), stop=arr(b.n, fill=97.0), be_trigger_pts=2.0)))
    assert tr.exit_bar == 3 and tr.exit_reason == "stop" and tr.exit_price == 99.75 and close(tr.net_pts, -0.25 - 0.75)
    assert tr.stop_price == 97.0 and close(tr.risk_pts, 3.0)        # the trades table keeps the INITIAL stop
    # trigger not reached (best 102 < +2.5): stop stays at 97
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {0: 1}), stop=arr(b.n, fill=97.0), be_trigger_pts=2.5)))
    assert tr.exit_reason == "eod"
    # be_offset_pts 0.5: stop to 100.5; bar 3 opens at 101 and falls through 100.5: out at 100.25
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {0: 1}), stop=arr(b.n, fill=97.0), be_trigger_pts=2.0, be_offset_pts=0.5)))
    assert tr.exit_price == 100.25 and close(tr.net_pts, 0.25 - 0.75)
    # trailing 1.5 behind the best closed-bar high: after bar 1 best 100.75 -> 99.25; after bar 2 best 102 -> 100.5
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {0: 1}), stop=arr(b.n, fill=97.0), trail_pts=1.5)))
    assert tr.exit_bar == 3 and tr.exit_price == 100.25
    # trail 0.7: after bar 1 the stop is 100.05; bar 2 (low 99.9) is stopped at 100.05 - 0.25, not at a stop that
    # would only exist after bar 2's own high (102 - 0.7 = 101.3)
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {0: 1}), stop=arr(b.n, fill=97.0), trail_pts=0.7)))
    assert tr.exit_bar == 2 and close(tr.exit_price, 100.05 - 0.25)
    # per-bar trail array (path a): the value on bar j tightens the stop from bar j+1; it never loosens
    tl = arr(b.n, fill=NAN)
    tl[1] = 99.0
    tl[2] = 100.25
    tl[3] = 90.0
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {0: 1}), stop=arr(b.n, fill=97.0), trail_long=tl)))
    assert tr.exit_bar == 3 and tr.exit_price == 100.0
    # R-based trigger: be_trigger_r=0.5 with risk 3 -> +1.5
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {0: 1}), stop=arr(b.n, fill=97.0), be_trigger_r=0.5)))
    assert tr.exit_bar == 3 and tr.exit_price == 99.75


@test
def a24_two_sided_orders_first_fill_cancels_the_other():
    rows = [("10:00", 100, 100.5, 99.5, 100),          # signal: buy stop 101, sell stop 99
            ("10:05", 100, 100.75, 98.75, 99.5),       # only the sell stop trades: short at 98.75
            ("10:10", 99.5, 101.5, 99.25, 101.25),     # would have filled the buy stop: cancelled.  Short stop 101 hit
            ("10:15", 101.25, 101.25, 101.25, 101.25), ("10:20", 101.25, 101.25, 101.25, 101.25)]
    b = B(rows)
    S = lambda: eng.Signals(long=dict(entry=mask(b.n, 0), order="stop", price=arr(b.n, fill=101.0), stop=arr(b.n, fill=99.0)),
                            short=dict(entry=mask(b.n, 0), order="stop", price=arr(b.n, fill=99.0), stop=arr(b.n, fill=101.0)))
    r = eng.run(b, S())
    tr = one_trade(r)
    assert tr.direction == -1 and tr.entry_price == 98.75 and tr.exit_bar == 2 and tr.exit_price == 101.25
    assert close(tr.net_pts, -2.5 - 0.75) and r.diag["orders"] == 2 and r.diag["fills"] == 1
    # both prices inside one bar: the one nearer to the open is taken; its stop (the other price) is then hit too
    rows2 = [("10:00", 100, 100.5, 99.5, 100), ("10:05", 100.5, 101.5, 98.5, 99.5), ("10:10", 99.5, 99.5, 99.5, 99.5),
             ("10:15", 99.5, 99.5, 99.5, 99.5)]
    b = B(rows2)
    tr = one_trade(eng.run(b, S()))
    assert tr.direction == 1 and tr.entry_price == 101.25 and tr.exit_price == 98.75 and tr.exit_bar == 1
    assert close(tr.net_pts, -2.5 - 0.75)


@test
def a25_callback_path_same_fills_and_timing():
    rows = [("10:00", 100, 100.5, 99.5, 100), ("10:05", 101, 103, 100.5, 102), ("10:10", 102, 104, 101, 103),
            ("10:15", 103, 105, 102, 104), ("10:20", 104, 104.5, 103.5, 104), ("10:25", 104, 104, 104, 104)]
    b = B(rows)
    seen = []

    def on_bar(ctx):
        seen.append((ctx.i, ctx.position, ctx.entry_price, ctx.bars_held, ctx.trades_today))
        if ctx.i == 0:
            assert ctx.buy_market(stop=99.0) is True
        if ctx.i == 2:
            ctx.set_stop(102.5)                      # decided at the close of bar 2: counts from bar 3
    r = eng.run(b, eng.Callback(on_bar))
    tr = one_trade(r)
    assert r.path == "callback" and tr.signal_bar == 0 and tr.entry_bar == 1 and tr.entry_price == 101.0
    # bar 2 (low 101) is not stopped by the stop set at its own close; bar 3 (open 103, low 102) is: 102.5 - 0.25
    assert tr.exit_bar == 3 and tr.exit_price == 102.25 and tr.exit_reason == "stop" and close(tr.net_pts, 1.25 - 0.75)
    assert seen[0] == (0, 0, None, 0, 0) and seen[1] == (1, 1, 101.0, 1, 1) and seen[2][:4] == (2, 1, 101.0, 2)
    assert seen[3][:2] == (3, 0)                     # the callback sees the flat state after the stop
    # ctx.exit(): out at the next bar's open
    def on_bar2(ctx):
        if ctx.i == 0:
            ctx.sell_limit(101.5, target_pts=1.0)
        if ctx.i == 2 and ctx.position != 0:
            ctx.exit()
    tr = one_trade(eng.run(b, eng.Callback(on_bar2)))
    # sell limit 101.5: bar 1 trades through (high 103) -> short at 101.5; entry bar: no target.  exit at bar 3 open
    assert tr.direction == -1 and tr.entry_price == 101.5 and tr.exit_bar == 3 and tr.exit_price == 103.0
    assert tr.exit_reason == "signal" and close(tr.net_pts, -1.5 - 0.75)
    # the same orders through path (a) give the same trade
    ra = eng.run(b, eng.Signals(short=dict(entry=mask(b.n, 0), order="limit", price=arr(b.n, fill=101.5)),
                                target_pts=1.0, exit_short=mask(b.n, 2)))
    ta = one_trade(ra)
    for col in ("entry_bar", "exit_bar", "entry_price", "exit_price", "exit_reason", "net_pts", "mae_pts", "mfe_pts"):
        assert ta[col] == tr[col], col
    # an entry order while a position is open is an error unless ctx.exit() is called too
    def on_bar3(ctx):
        if ctx.i in (0, 2):
            ctx.buy_market()
    try:
        eng.run(b, eng.Callback(on_bar3))
    except RuntimeError:
        pass
    else:
        raise AssertionError("entry order while in a position must raise")
    # a NaN price voids the order
    def on_bar4(ctx):
        if ctx.i == 0:
            assert ctx.buy_stop(NAN) is False
    r = eng.run(b, eng.Callback(on_bar4))
    assert len(r.trades) == 0 and r.diag["void"] == 1


@test
def a25a_callback_context_values_hand_computed():
    rows = [("10:00", 100, 100.5, 99.5, 100),
            ("10:05", 100, 101, 99.5, 100.5),          # long 100 (market from bar 0), stop 98
            ("10:10", 100.5, 102, 100, 101.5),         # at this close the target is set to 102.75
            ("10:15", 101.5, 103, 101, 102.5),         # through 102.75: out at 102.75, +2.75 gross, +2.00 net
            ("10:20", 102.5, 103, 102, 102.5),         # buy stop 103.5 and sell stop 101.5 wait; the buy stop is cancelled
            ("10:25", 102.5, 104, 101.25, 101.5),      # 104 would have filled the buy stop; the sell stop fills: 101.25
            ("10:30", 101.5, 101.75, 100.5, 101),
            ("10:35", 101, 101, 101, 101)]
    b = B(rows)
    log = {}

    def on_bar(ctx):
        i = ctx.i
        log[i] = dict(pos=ctx.position, entry=ctx.entry_price, eb=ctx.entry_bar, stop=ctx.stop, tgt=ctx.target, held=ctx.bars_held,
                      mfe=ctx.mfe, mae=ctx.mae, open=ctx.open_pts, risk=ctx.risk, pl=ctx.pending_long, ps=ctx.pending_short,
                      tt=ctx.trades_today, net=ctx.net_today, n=ctx.n_trades, exiting=ctx.exiting)
        if i == 0:
            ctx.buy_market(stop=98.0)
        elif i == 2:
            ctx.set_target(102.75)
        elif i == 3:
            ctx.buy_stop(103.5)
            ctx.sell_stop(101.5)
        elif i == 4:
            ctx.cancel(1)
    r = eng.run(b, eng.Callback(on_bar))
    tr = r.trades
    assert len(tr) == 2 and r.diag["orders"] == 3 and r.diag["fills"] == 2
    assert log[0]["pos"] == 0 and log[0]["entry"] is None and log[0]["tt"] == 0 and math.isnan(log[0]["risk"])
    a = log[1]
    assert (a["pos"], a["entry"], a["eb"], a["stop"], a["tgt"], a["held"]) == (1, 100.0, 1, 98.0, None, 1)
    assert close(a["mfe"], 1.0) and close(a["mae"], 0.5) and close(a["open"], 0.5) and close(a["risk"], 2.0) and a["tt"] == 1
    a = log[2]
    assert close(a["mfe"], 2.0) and close(a["mae"], 0.5) and close(a["open"], 1.5) and a["held"] == 2 and a["n"] == 0
    a = log[3]
    assert a["pos"] == 0 and a["entry"] is None and a["n"] == 1 and close(a["net"], 2.0) and a["tt"] == 1 and not a["pl"]
    assert log[4]["pl"] and log[4]["ps"] and log[4]["pos"] == 0
    a = log[5]
    assert (a["pos"], a["entry"], a["eb"]) == (-1, 101.25, 5) and not a["pl"] and not a["ps"] and a["tt"] == 2 and close(a["net"], 2.0)
    # entry bar of a stop entry: the adverse extreme counts (high 104 against a short at 101.25), favourable: close only
    assert close(a["mae"], 2.75) and close(a["mfe"], 0.0) and close(a["open"], -0.25)
    t0, t1 = tr.iloc[0], tr.iloc[1]
    assert t0.exit_reason == "target" and t0.exit_price == 102.75 and close(t0.net_pts, 2.0) and math.isnan(t0.target_price)
    assert t1.direction == -1 and t1.signal_bar == 3 and t1.entry_bar == 5 and t1.exit_reason == "eod" and t1.exit_price == 101.0
    assert close(t1.net_pts, 0.25 - 0.75)


@test
def a26_nan_voids_signal_and_market_price_is_ignored():
    rows = [("10:00", 100, 100.5, 99.5, 100), ("10:05", 101, 103, 100.5, 102), ("10:10", 102, 104, 101, 103),
            ("10:15", 103, 105, 102, 104), ("10:20", 104, 104, 104, 104)]
    b = B(rows)
    st = arr(b.n, fill=NAN)
    st[2] = 100.0
    r = eng.run(b, eng.Signals(arr(b.n, {0: 1, 2: 1}), stop=st))
    tr = one_trade(r)
    assert r.diag["void"] == 1 and tr.signal_bar == 2 and tr.entry_bar == 3
    # +inf stop = "no stop on this bar"
    r = eng.run(b, eng.Signals(arr(b.n, {0: 1}), stop=arr(b.n, fill=float("-inf"))))
    tr = one_trade(r)
    assert math.isnan(tr.stop_price) and math.isnan(tr.risk_pts) and math.isnan(tr.r_multiple) and tr.exit_reason == "eod"
    # a market order ignores the price array
    r = eng.run(b, eng.Signals(arr(b.n, {0: 1}), price=arr(b.n, fill=NAN), max_bars=1))
    assert one_trade(r).entry_price == 101.0


@test
def a27_mae_mfe_hand_computed():
    rows = [("10:00", 100, 100.5, 99.5, 100),
            ("10:05", 100, 100.5, 98.5, 99),           # entry 100 (market): full bar counts: low 98.5, high 100.5
            ("10:10", 99, 103, 98.75, 102.5),
            ("10:15", 102.5, 104.25, 99.25, 99.5),     # target 104 traded through: favourable up to 104; the whole
                                                       #   low of the exit bar counts as adverse (98.5 stays the worst)
            ("10:20", 99.5, 99.5, 99.5, 99.5), ("10:25", 99.5, 99.5, 99.5, 99.5)]
    b = B(rows)
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {0: 1}), target=arr(b.n, fill=104.0))))
    assert tr.exit_reason == "target" and close(tr.mae_pts, 1.5) and close(tr.mfe_pts, 4.0)
    # short with a stop: entry 100; highs 100.5, 103 -> stop 102.5 hit in bar 2 (opens 99): adverse up to the stop
    # price 102.5 = 2.5; favourable: bar 1 low 98.5 = 1.5 and only the OPEN of the stop bar (99 -> 1.0)
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {0: -1}), stop=arr(b.n, fill=102.5))))
    assert tr.exit_reason == "stop" and tr.exit_bar == 2 and close(tr.mae_pts, 2.5) and close(tr.mfe_pts, 1.5)
    # stop bar whose open is the best price of the trade: long, entry 100, stop 98.6; bar 2 opens 99 ... no; use a
    # dedicated case: entry 100; bar 2 opens at 101.5 (best) and falls to the stop at 99
    rows2 = [("10:00", 100, 100.5, 99.5, 100), ("10:05", 100, 100.5, 99.5, 100.25), ("10:10", 101.5, 104, 98.5, 99),
             ("10:15", 99, 99, 99, 99), ("10:20", 99, 99, 99, 99)]
    b2 = B(rows2)
    tr = one_trade(eng.run(b2, eng.Signals(arr(b2.n, {0: 1}), stop=arr(b2.n, fill=99.0))))
    # the high 104 of the stop bar is NOT counted as favourable (it may have come after the stop): only its open
    assert tr.exit_bar == 2 and close(tr.mfe_pts, 1.5) and close(tr.mae_pts, 1.0) and tr.exit_price == 98.75
    assert (eng.run(b, eng.Signals(arr(b.n, {0: 1}), max_bars=2)).trades[["mae_pts", "mfe_pts"]] >= 0).all().all()


# =====================================================================================================================
# B. LOOKAHEAD HUNT
# =====================================================================================================================
def _all_helpers(b):
    """Every helper of ENGINE.md section 3 and every per-bar field of Bars, as float arrays."""
    out = {}
    for name, p in (("prior", eng.prior_rth(b)), ("priorNC", eng.prior_rth(b, require_complete=False))):
        for k in p:
            out[f"{name}_{k}"] = p[k]
    out["on_h"], out["on_l"] = eng.overnight_range(b)
    for mins in (5, 15, 30, 60):
        out[f"or{mins}_h"], out[f"or{mins}_l"] = eng.opening_range(b, "09:30", mins)
        out[f"orNF{mins}_h"], out[f"orNF{mins}_l"] = eng.opening_range(b, "09:30", mins, require_full=False)
    out["orE_h"], out["orE_l"] = eng.opening_range(b, "18:00", 60)
    out["orN_h"], out["orN_l"] = eng.opening_range(b, "03:00", 30)
    out["rth_open"] = eng.rth_open(b)
    out["gap"] = eng.gap(b)
    out["gap_pct"] = eng.gap(b, pct=True)
    for k, v in eng.floor_pivots(b).items():
        out["fp_" + k] = v
    for k, v in eng.camarilla_pivots(b).items():
        out["cam_" + k] = v
    out["datr"] = eng.daily_atr(b, 14)
    out["datr_sma"] = eng.daily_atr(b, 5, "sma")
    out["sh"], out["sl"] = eng.session_high_low(b)
    out["sh18"], out["sl18"] = eng.session_high_low(b, "18:00")
    out["twap"] = eng.twap_vwap_proxy(b)
    out["twap18"], out["twap18sd"] = eng.twap_vwap_proxy(b, "18:00", bands=True)
    out["lagdays"] = eng.lag_days_to_bars(b, b.days["rth_close"].to_numpy())
    out["sma"] = eng.sma(b.c, 20)
    out["ema"] = eng.ema(b.c, 20)
    out["wilder"] = eng.wilder(b.c, 14)
    out["atr"] = eng.atr(b.h, b.l, b.c, 14)
    out["rsi"] = eng.rsi(b.c, 14)
    out["adx"], out["pdi"], out["mdi"] = eng.adx(b.h, b.l, b.c, 14)
    out["bb_m"], out["bb_u"], out["bb_l"] = eng.bollinger(b.c, 20, 2.0)
    out["k_m"], out["k_u"], out["k_l"] = eng.keltner(b.h, b.l, b.c)
    out["don_h"], out["don_l"] = eng.donchian(b.h, b.l, 20)
    out["donx_h"], out["donx_l"] = eng.donchian(b.h, b.l, 20, include_current=False)
    out["rmax"] = eng.rolling_max(b.h, 10)
    out["rmin"] = eng.rolling_min(b.l, 10)
    out["rstd"] = eng.rolling_std(b.c, 10)
    out["lag3"] = eng.lag(b.c, 3)
    out["xa"] = eng.cross_above(eng.sma(b.c, 5), eng.sma(b.c, 20)).astype(float)
    out["xb"] = eng.cross_below(eng.sma(b.c, 5), eng.sma(b.c, 20)).astype(float)
    out["m_atr"] = eng.masked(b.rth, lambda h, l, c: eng.atr(h, l, c, 14), b.h, b.l, b.c)
    out["m_atr_ff"] = eng.masked(b.rth, lambda h, l, c: eng.atr(h, l, c, 14), b.h, b.l, b.c, ffill=True)
    for k in ("date", "mod", "wd", "end_mod", "tday_id", "tday_wd", "tmin", "tmin_end", "rth", "day_idx", "t_end"):
        out["f_" + k] = np.asarray(getattr(b, k)).astype("float64")
    return out


def _slice(res, start_frac, nb, anchor="00:00"):
    full = eng.load_bars(res, anchor)
    s = int(full.n * start_frac)
    return eng.Bars(full.t[s:s + nb], full.o[s:s + nb], full.h[s:s + nb], full.l[s:s + nb], full.c[s:s + nb], res,
                    tmin_end=full.tmin_end[s:s + nb], rth_counts=eng.rth_counts_1m())


def _structural_cuts(base, rng, n_random, n_days):
    cuts = set(int(x) for x in rng.integers(base.n // 2, base.n, size=n_random))
    d = base.days
    for j in rng.integers(len(d) // 2, len(d) - 1, size=n_days):
        r = d.iloc[int(j)]
        if r.rth_first >= 0:        # the first regular-session bar, inside the opening range, the last one, the next
            cuts |= {int(r.rth_first), int(r.rth_first) + 1, int(r.rth_first) + 3, int(r.rth_last), int(r.rth_last) + 1}
        cuts |= {int(r["first"]) + 1, int(r["last"]), int(r["last"]) + 1}
    return sorted(k for k in cuts if 1 <= k <= base.n)


@test
def b01_every_helper_is_unchanged_when_later_bars_are_removed():
    for res, nb, frac in ((5, 60000, 0.33), (5, 30000, 0.90), (1, 60000, 0.55), (15, 20000, 0.2), (60, 8000, 0.6)):
        base = _slice(res, frac, nb)
        ref = _all_helpers(base)
        rng = np.random.default_rng(res + nb)
        cuts = _structural_cuts(base, rng, 14, 5)
        for k in cuts:
            got = _all_helpers(base.truncate(k))
            for name, full in ref.items():
                assert eq_arr(full[:k], got[name], 1e-7), f"res {res}: helper {name} at bars < {k} depends on later bars"


@test
def b02_session_helpers_against_brute_force_on_real_days():
    b = eng.load_bars(5)
    d = b.days
    nd = len(d)
    first, last = d["first"].to_numpy(), d["last"].to_numpy()
    tmin, te = b.tmin.astype(int), b.tmin_end.astype(int)
    H, L, O, C = b.h, b.l, b.o, b.c
    sess = []
    for k in range(nd):
        r = [i for i in range(first[k], last[k] + 1) if tmin[i] >= 930 and te[i] <= 1320]
        sess.append(dict(o=O[r[0]], h=H[r].max(), l=L[r].min(), c=C[r[-1]], first=r[0], last=r[-1]) if r else None)
    complete = d["complete"].to_numpy()
    comp_idx = [k for k in range(nd) if complete[k] and sess[k] is not None]
    tr = []
    for q, k in enumerate(comp_idx):
        s = sess[k]
        pc = None if q == 0 else sess[comp_idx[q - 1]]["c"]
        tr.append(s["h"] - s["l"] if pc is None else max(s["h"] - s["l"], abs(s["h"] - pc), abs(s["l"] - pc)))
    atr_day, a = {}, None
    for q, k in enumerate(comp_idx):
        if q == 13:
            a = sum(tr[:14]) / 14
        elif q > 13:
            a = a + (tr[q] - a) / 14
        atr_day[k] = a
    pr, prn = eng.prior_rth(b), eng.prior_rth(b, require_complete=False)
    orh, orl = eng.opening_range(b, "09:30", 30)
    orh15, orl15 = eng.opening_range(b, "09:30", 15, require_full=False)
    onh, onl = eng.overnight_range(b)
    ro, gp = eng.rth_open(b), eng.gap(b)
    sh, sl = eng.session_high_low(b)
    tw, twsd = eng.twap_vwap_proxy(b, bands=True)
    datr = eng.daily_atr(b, 14)
    rng = np.random.default_rng(5)
    days = sorted(set(rng.integers(20, nd, 120).tolist()) | set(range(nd - 3, nd)) | set(range(15, 25)))
    nan2 = (NAN, NAN)
    for k in days:
        i0, i1 = first[k], last[k] + 1
        p = k - 1
        while p >= 0 and sess[p] is None:
            p -= 1
        assert p < 0 or sess[p]["last"] < i0                    # the prior session lies wholly before this trading day
        e4 = (NAN,) * 4 if p < 0 else (sess[p]["o"], sess[p]["h"], sess[p]["l"], sess[p]["c"])
        e4c = e4 if (p >= 0 and complete[p]) else (NAN,) * 4
        q = k - 1
        while q >= 0 and q not in atr_day:
            q -= 1
        ea = NAN if (q < 0 or atr_day[q] is None) else atr_day[q]
        assert eq_arr(datr[i0:i1], np.full(i1 - i0, ea)), f"daily_atr day {k}"
        w30 = [i for i in range(i0, i1) if tmin[i] >= 930 and te[i] <= 960]
        w15 = [i for i in range(i0, i1) if tmin[i] >= 930 and te[i] <= 945]
        for i in range(i0, i1):
            assert eq_arr((prn["open"][i], prn["high"][i], prn["low"][i], prn["close"][i]), e4), f"prior_rth day {k}"
            assert eq_arr((pr["open"][i], pr["high"][i], pr["low"][i], pr["close"][i]), e4c), f"prior_rth(complete) day {k}"
            # opening range: NaN on every bar before the one that completes the window
            e = (H[w30].max(), L[w30].min()) if (te[i] >= 960 and len(w30) == 6) else nan2
            assert eq_arr((orh[i], orl[i]), e), f"opening_range 30 day {k} bar {i}"
            assert not (te[i] >= 960 and len(w30) == 6) or max(w30) <= i
            e = (H[w15].max(), L[w15].min()) if (te[i] >= 945 and w15) else nan2
            assert eq_arr((orh15[i], orl15[i]), e), f"opening_range 15 day {k} bar {i}"
            ov = [j for j in range(i0, i + 1) if te[j] <= 930]
            assert eq_arr((onh[i], onl[i]), (H[ov].max(), L[ov].min()) if ov else nan2), f"overnight_range day {k}"
            ss = [j for j in range(i0, i + 1) if tmin[j] >= 930]
            assert eq_arr((sh[i], sl[i]), (H[ss].max(), L[ss].min()) if ss else nan2), f"session_high_low day {k}"
            if ss:
                tp = (H[ss] + L[ss] + C[ss]) / 3.0
                assert close(tw[i], tp.mean(), 1e-6) and close(twsd[i], tp.std(), 1e-5), f"twap day {k}"
            else:
                assert math.isnan(tw[i]) and math.isnan(twsd[i])
            s = sess[k]
            e = s["o"] if (s is not None and i >= s["first"] and b.mod[s["first"]] <= 575) else NAN
            assert eq_arr(ro[i], e), f"rth_open day {k}"
            assert eq_arr(gp[i], e - e4c[3]), f"gap day {k}"
    # pivots are pure functions of the prior session
    fp, cam = eng.floor_pivots(b), eng.camarilla_pivots(b)
    Hh, Ll, Cc = pr["high"], pr["low"], pr["close"]
    P = (Hh + Ll + Cc) / 3.0
    assert eq_arr(fp["P"], P) and eq_arr(fp["R1"], 2 * P - Ll) and eq_arr(fp["S1"], 2 * P - Hh)
    assert eq_arr(fp["R2"], P + Hh - Ll) and eq_arr(fp["S2"], P - Hh + Ll)
    assert eq_arr(fp["R3"], Hh + 2 * (P - Ll)) and eq_arr(fp["S3"], Ll - 2 * (Hh - P))
    for k, dv in ((1, 12), (2, 6), (3, 4), (4, 2)):
        assert eq_arr(cam[f"R{k}"], Cc + (Hh - Ll) * 1.1 / dv) and eq_arr(cam[f"S{k}"], Cc - (Hh - Ll) * 1.1 / dv)


@test
def b03_session_helpers_hand_computed_on_synthetic_days():
    def day(d, prev, lo, hi, n_rth=78):
        rows = [(f"{prev} 18:00", 50, 52, 49, 51), (f"{prev} 23:55", 51, 55, 50, 54), (f"{d} 00:00", 54, 56, 53, 55),
                (f"{d} 09:25", 55, 57, 48, 56)]
        px = lo
        for k in range(n_rth):
            m = 570 + 5 * k
            rows.append((f"{d} {m // 60:02d}:{m % 60:02d}", px, px + 2, px - 1, px + 1))
            px += 1
        rows.append((f"{d} 16:00", px, px + 30, px - 30, px))        # after the regular session: in no session level
        return rows
    rows = day("2021-06-15", "2021-06-14", 100, 0) + day("2021-06-16", "2021-06-15", 200, 0) + day("2021-06-17", "2021-06-16", 300, 0)
    b = B(rows)
    # regular session of each day: open lo, high lo+77+2, low lo-1, close lo+78
    d = b.days
    assert list(d["rth_open"]) == [100, 200, 300] and list(d["rth_high"]) == [179, 279, 379]
    assert list(d["rth_low"]) == [99, 199, 299] and list(d["rth_close"]) == [178, 278, 378]
    pr = eng.prior_rth(b, require_complete=False)
    i_wed_eve = [i for i in range(b.n) if et_str(b.et[i]) == "2021-06-15 18:00"][0]
    i_wed_0930 = [i for i in range(b.n) if et_str(b.et[i]) == "2021-06-16 09:30"][0]
    i_tue_1600 = [i for i in range(b.n) if et_str(b.et[i]) == "2021-06-15 16:00"][0]
    # Tuesday has no prior session: NaN, also on its last bar (it must not show Tuesday's own session)
    assert math.isnan(pr["high"][i_tue_1600]) and math.isnan(pr["close"][i_tue_1600])
    # from Tuesday 18:00 (Wednesday's trading day) the prior session is Tuesday's
    for i in (i_wed_eve, i_wed_0930, i_wed_0930 + 30):
        assert (pr["open"][i], pr["high"][i], pr["low"][i], pr["close"][i]) == (100, 179, 99, 178)
    # opening range 09:30-10:00 of Wednesday: bars 200..205 -> high 205+2, low 199; NaN until the 09:55 bar closes
    orh, orl = eng.opening_range(b, "09:30", 30)
    assert all(math.isnan(orh[i]) for i in range(i_wed_eve, i_wed_0930 + 5))
    assert (orh[i_wed_0930 + 5], orl[i_wed_0930 + 5]) == (207, 199) and orh[i_wed_0930 + 40] == 207
    # overnight range of Wednesday: 18:00, 23:55, 00:00, 09:25 bars -> running high 52, 55, 56, 57; low 49, 49, 49, 48
    onh, onl = eng.overnight_range(b)
    assert list(onh[i_wed_eve:i_wed_eve + 5]) == [52, 55, 56, 57, 57] and list(onl[i_wed_eve:i_wed_eve + 5]) == [49, 49, 49, 48, 48]
    # rth_open and gap: NaN before 09:30, then 200 and 200 - 178
    ro, g = eng.rth_open(b), eng.gap(b, require_complete=False)
    assert math.isnan(ro[i_wed_0930 - 1]) and ro[i_wed_0930] == 200 and g[i_wed_0930] == 22 and math.isnan(g[i_wed_0930 - 1])
    # daily ATR(2, sma) for Thursday = mean of the true ranges of Tuesday (80) and Wednesday (max(80, |279-178|, |199-178|) = 101)
    da = eng.daily_atr(b, 2, "sma")
    i_thu = [i for i in range(b.n) if et_str(b.et[i]) == "2021-06-17 09:30"][0]
    assert math.isnan(da[i_wed_0930]) and close(da[i_thu], 90.5) and close(da[i_thu - 4], 90.5)
    # lag_days_to_bars gives yesterday's value, never today's
    ld = eng.lag_days_to_bars(b, d["rth_close"].to_numpy())
    assert math.isnan(ld[i_tue_1600]) and ld[i_wed_0930] == 178 and ld[i_thu] == 278
    # running session high/low and the time-weighted proxy include the current bar and nothing later
    sh, sl = eng.session_high_low(b)
    assert (sh[i_wed_0930], sl[i_wed_0930]) == (202, 199) and (sh[i_wed_0930 + 1], sl[i_wed_0930 + 1]) == (203, 199)
    tw = eng.twap_vwap_proxy(b)
    assert close(tw[i_wed_0930], (202 + 199 + 201) / 3) and close(tw[i_wed_0930 + 1], ((202 + 199 + 201) / 3 + (203 + 200 + 202) / 3) / 2)


@test
def b04_series_indicators_against_plain_loops():
    b = eng.load_bars(5)
    s, n = 400000, 1500
    h, l, c = (np.array(x[s:s + n]) for x in (b.h, b.l, b.c))

    def L_sma(x, k):
        return [NAN if i < k - 1 else sum(x[i - k + 1:i + 1]) / k for i in range(len(x))]

    def L_ema(x, k):
        a, y, out = 2 / (k + 1), x[0], []
        for i, v in enumerate(x):
            y = v if i == 0 else y + a * (v - y)
            out.append(y if i >= k - 1 else NAN)
        return out

    def L_wilder(x, k):
        out, y = [NAN] * len(x), None
        for i in range(len(x)):
            if i == k - 1:
                y = sum(x[:k]) / k
                out[i] = y
            elif i >= k:
                y = y + (x[i] - y) / k
                out[i] = y
        return out

    def L_tr(h, l, c):
        return [h[i] - l[i] if i == 0 else max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(len(h))]

    assert eq_arr(eng.sma(c, 20), L_sma(c, 20)) and eq_arr(eng.ema(c, 20), L_ema(c, 20)) and eq_arr(eng.wilder(c, 14), L_wilder(c, 14))
    assert eq_arr(eng.true_range(h, l, c), L_tr(h, l, c)) and eq_arr(eng.atr(h, l, c, 14), L_wilder(L_tr(h, l, c), 14))
    up = [max(c[i] - c[i - 1], 0) for i in range(1, n)]
    dn = [max(c[i - 1] - c[i], 0) for i in range(1, n)]
    au, ad = L_wilder(up, 14), L_wilder(dn, 14)
    rsi = [NAN] + [NAN if u != u else (50.0 if (d == 0 and u == 0) else 100.0 if d == 0 else 100 - 100 / (1 + u / d)) for u, d in zip(au, ad)]
    assert eq_arr(eng.rsi(c, 14), rsi)
    pdm, mdm = [], []
    for i in range(1, n):
        u_, d_ = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm.append(u_ if (u_ > d_ and u_ > 0) else 0.0)
        mdm.append(d_ if (d_ > u_ and d_ > 0) else 0.0)
    st, sp_, sm = L_wilder(L_tr(h, l, c)[1:], 14), L_wilder(pdm, 14), L_wilder(mdm, 14)
    pdi = [NAN if a != a else 100 * p / a for a, p in zip(st, sp_)]
    mdi = [NAN if a != a else 100 * m / a for a, m in zip(st, sm)]
    dx = [NAN if p != p else (0.0 if p + m == 0 else 100 * abs(p - m) / (p + m)) for p, m in zip(pdi, mdi)]
    f = next(i for i, v in enumerate(dx) if v == v)
    adx = [NAN] + [NAN] * f + L_wilder(dx[f:], 14)
    a1, a2, a3 = eng.adx(h, l, c, 14)
    assert eq_arr(a1, adx) and eq_arr(a2, [NAN] + pdi) and eq_arr(a3, [NAN] + mdi)
    m_, u_, lo_ = eng.bollinger(c, 20, 2.0)
    sd = np.array([NAN if i < 19 else float(np.std(c[i - 19:i + 1])) for i in range(n)])
    assert eq_arr(m_, L_sma(c, 20)) and eq_arr(u_, np.array(L_sma(c, 20)) + 2 * sd, 1e-6) and eq_arr(lo_, np.array(L_sma(c, 20)) - 2 * sd, 1e-6)
    km, ku, kl = eng.keltner(h, l, c, 20, 10, 2.0)
    ka = np.array(L_wilder(L_tr(h, l, c), 10))
    assert eq_arr(km, L_ema(c, 20)) and eq_arr(ku, np.array(L_ema(c, 20)) + 2 * ka) and eq_arr(kl, np.array(L_ema(c, 20)) - 2 * ka)
    dh, dl = eng.donchian(h, l, 20)
    xh, xl = eng.donchian(h, l, 20, include_current=False)
    assert eq_arr(dh, [NAN if i < 19 else h[i - 19:i + 1].max() for i in range(n)])
    assert eq_arr(dl, [NAN if i < 19 else l[i - 19:i + 1].min() for i in range(n)])
    assert eq_arr(xh, [NAN if i < 20 else h[i - 20:i].max() for i in range(n)])       # the n bars BEFORE the current one
    assert eq_arr(xl, [NAN if i < 20 else l[i - 20:i].min() for i in range(n)])
    assert eq_arr(eng.lag(c, 3), [NAN] * 3 + list(c[:-3]))
    try:
        eng.lag(c, -1)
    except ValueError:
        pass
    else:
        raise AssertionError("lag(-1) must be refused")
    fs, ss = eng.sma(c, 5), eng.sma(c, 20)
    xa = [False] + [bool(fs[i] > ss[i] and fs[i - 1] <= ss[i - 1]) for i in range(1, n)]
    xb = [False] + [bool(fs[i] < ss[i] and fs[i - 1] >= ss[i - 1]) for i in range(1, n)]
    assert list(eng.cross_above(fs, ss)) == xa and list(eng.cross_below(fs, ss)) == xb and sum(xa) > 10


@test
def b05_resampled_bars_hold_only_their_own_minutes():
    z = raw_1m()
    t, o, h, l, c = (z[k] for k in "tohlc")
    r5 = eng.resample_1m(t, o, h, l, c, 5)
    b5 = eng.load_bars(5)
    assert all(np.array_equal(r5[k], getattr(b5, k)) for k in "ohlc") and np.array_equal(r5["tmin_end"], b5.tmin_end)
    # brute force on three windows: a spring DST change with 16:15+ minutes in the raw data (2016), a fall change
    # (2021) and a holiday week (2012), for resolutions that divide the day and for some that do not
    for day0 in ("2016-03-09", "2021-11-03", "2012-12-21"):
        s = int(np.searchsorted(t, ts(day0 + " 00:00")))
        sl = slice(s, s + 9000)
        tt, oo, hh, ll, cc = t[sl], o[sl], h[sl], l[sl], c[sl]
        mods = []
        for x in tt:
            dd = datetime.fromtimestamp(int(x), tz=timezone.utc).astimezone(NYZ)
            mods.append(dd.hour * 60 + dd.minute)
        for minutes, anchor in ((2, "00:00"), (3, "00:00"), (5, "00:00"), (15, "00:00"), (30, "00:00"), (60, "00:00"),
                                (60, "09:30"), (120, "09:30"), (240, "00:00"), (45, "09:30"),
                                (7, "00:00"), (13, "00:04"), (50, "09:30"), (65, "09:30"), (130, "09:30"), (195, "09:30"),
                                (390, "09:30"), (25, "18:00")):
            rr = eng.resample_1m(tt, oo, hh, ll, cc, minutes, anchor)
            bb = eng.Bars(rr["t"], rr["o"], rr["h"], rr["l"], rr["c"], minutes, tmin_end=rr["tmin_end"])
            tag = f"{day0} {minutes}m anchor {anchor}"
            # every bar: stamped inside the trading day, ends after it opens and not after the next bar opens
            assert (bb.t_end[:-1] <= bb.t[1:]).all(), f"{tag}: a bar's nominal end lies after the next bar's open"
            assert ((bb.t_end - bb.t) <= minutes * 60).all() and ((bb.t_end - bb.t) > 0).all(), tag
            # every kept minute belongs to exactly one bar, lies in [bar open, nominal end), and the bar's OHLC are
            # exactly those minutes
            keep = [i for i, m in enumerate(mods) if not (975 <= m < 1080)]
            kt = tt[keep]
            pos = np.searchsorted(bb.t, kt, side="right") - 1
            assert (pos >= 0).all() and (kt < bb.t_end[pos]).all(), f"{tag}: a minute lies outside its bar"
            for j in range(bb.n):
                mm = np.asarray(keep)[pos == j]
                assert len(mm), f"{tag}: empty bar"
                assert bb.o[j] == oo[mm[0]] and bb.c[j] == cc[mm[-1]] and bb.h[j] == hh[mm].max() and bb.l[j] == ll[mm].min(), tag
            # the grid: a bucket starts at anchor + k * minutes on the New York clock, or at the 18:00 open, or (only
            # when the resolution does not divide a day) at midnight, where the grid starts again
            on_grid = (bb.mod.astype(int) - eng.hm(anchor)) % minutes == 0
            assert (on_grid | (bb.mod == 1080) | ((bb.mod == 0) & (1440 % minutes != 0))).all(), f"{tag}: bar not on the grid"
            assert int(bb.tmin_end.max()) <= 1335
            if 1440 % minutes:                    # no bar crosses midnight
                assert not ((bb.tmin < 360) & (bb.tmin_end > 360)).any(), tag
    # the anchored regular session: 65-minute bars from 09:30 give exactly six regular-session bars per full day
    for res, per_day in ((65, 6), (130, 3), (195, 2), (390, 1)):
        bb = eng.load_bars(res, anchor="09:30")
        d = bb.days
        full = d["complete"].to_numpy() & (d["rth_first_mod"].to_numpy() == 570)
        cnt = np.bincount(bb.day_idx[bb.rth], minlength=len(d))
        assert (cnt[full] == per_day).mean() > 0.99, (res, np.bincount(cnt[full]))
        assert (bb.t_end[:-1] <= bb.t[1:]).all()
    # resampling the first k minutes gives the same finished bars as resampling everything
    sl = slice(2_000_000, 2_020_000)
    for minutes in (5, 15, 60, 65):
        full = eng.resample_1m(t[sl], o[sl], h[sl], l[sl], c[sl], minutes, "09:30")
        for k in (1234, 9999, 17001):
            part = eng.resample_1m(t[sl][:k], o[sl][:k], h[sl][:k], l[sl][:k], c[sl][:k], minutes, "09:30")
            m = len(part["t"]) - 1
            assert all(np.array_equal(part[key][:m], full[key][:m]) for key in ("t", "o", "h", "l", "c", "tmin_end"))
            assert part["t"][m] == full["t"][m] and part["o"][m] == full["o"][m]


@test
def b05a_resampling_hand_computed_around_midnight_and_the_break():
    def minutes(day, start, end):
        h0, m0 = int(start[:2]), int(start[3:])
        n = (int(end[:2]) * 60 + int(end[3:])) - (h0 * 60 + m0)
        return [ts(f"{day} {(h0 * 60 + m0 + k) // 60:02d}:{(h0 * 60 + m0 + k) % 60:02d}") for k in range(n)]
    # Tue 2021-06-15 23:50 .. 23:59 and Wed 00:00 .. 00:10: price = minute counter 0..20
    t = minutes("2021-06-15", "23:50", "24:00") + minutes("2021-06-16", "00:00", "00:11")
    px = np.arange(len(t), dtype="float64")
    hi, lo = px + 0.5, px - 0.5
    # 5-minute bars (divides a day): 23:50, 23:55, 00:00, 00:05, 00:10
    r = eng.resample_1m(t, px, hi, lo, px, 5)
    assert list(r["t"]) == [ts("2021-06-15 23:50"), ts("2021-06-15 23:55"), ts("2021-06-16 00:00"), ts("2021-06-16 00:05"),
                            ts("2021-06-16 00:10")]
    assert list(r["o"]) == [0, 5, 10, 15, 20] and list(r["c"]) == [4, 9, 14, 19, 20] and list(r["h"]) == [4.5, 9.5, 14.5, 19.5, 20.5]
    assert list(r["l"]) == [-0.5, 4.5, 9.5, 14.5, 19.5] and list(r["tmin_end"]) == [355, 360, 365, 370, 375]
    # 60-minute bars anchored at 09:30: the 23:30 bucket runs across midnight to 00:30 as ONE bar
    r = eng.resample_1m(t, px, hi, lo, px, 60, "09:30")
    assert list(r["t"]) == [ts("2021-06-15 23:30")] and list(r["tmin_end"]) == [390] and r["o"][0] == 0 and r["c"][0] == 20
    # 7-minute bars (do not divide a day): the grid 00:00 + 7k restarts at midnight.  23:48 bucket holds 23:50-23:54,
    # the 23:55 bucket holds 23:55-23:59 and ENDS at midnight (not at 00:02); then 00:00 and 00:07
    r = eng.resample_1m(t, px, hi, lo, px, 7)
    assert list(r["t"]) == [ts("2021-06-15 23:48"), ts("2021-06-15 23:55"), ts("2021-06-16 00:00"), ts("2021-06-16 00:07")]
    assert list(r["o"]) == [0, 5, 10, 17] and list(r["c"]) == [4, 9, 16, 20] and list(r["tmin_end"]) == [355, 360, 367, 374]
    # 65-minute bars anchored at 09:30 (grid ..., 23:35, then again 00:50, 01:55, ...): the bar after midnight is
    # stamped 00:00, not 23:45 of the day before, and the bar before it ends at midnight
    r = eng.resample_1m(t, px, hi, lo, px, 65, "09:30")
    assert list(r["t"]) == [ts("2021-06-15 23:35"), ts("2021-06-16 00:00")]
    assert list(r["o"]) == [0, 10] and list(r["c"]) == [9, 20] and list(r["tmin_end"]) == [360, 410]
    b = eng.Bars(r["t"], r["o"], r["h"], r["l"], r["c"], 65, tmin_end=r["tmin_end"])
    assert list(b.t_end) == [ts("2021-06-16 00:00"), ts("2021-06-16 00:50")] and [str(x) for x in b.date] == ["2021-06-15", "2021-06-16"]
    # the same grid in the regular session: 09:30, 10:35, 11:40, 12:45, 13:50, 14:55 (ends 16:00), then 16:00-16:15
    t2 = minutes("2021-06-16", "09:25", "16:20")
    p2 = np.arange(len(t2), dtype="float64")
    r = eng.resample_1m(t2, p2, p2, p2, p2, 65, "09:30")
    hhmm = [datetime.fromtimestamp(int(x), tz=NYZ).strftime("%H:%M") for x in r["t"]]
    assert hhmm == ["08:25", "09:30", "10:35", "11:40", "12:45", "13:50", "14:55", "16:00"]
    assert list(r["tmin_end"]) == [930, 995, 1060, 1125, 1190, 1255, 1320, 1335]
    assert r["o"][1] == 5 and r["c"][6] == 5 + 390 - 1 and r["c"][7] == 5 + 390 + 14        # 16:14 is the last minute used
    # the evening open: a 240-minute bucket 16:00-20:00 is cut at 16:15 and starts again at 18:00
    t3 = minutes("2021-06-16", "16:10", "18:03")
    p3 = np.arange(len(t3), dtype="float64")
    r = eng.resample_1m(t3, p3, p3, p3, p3, 240)
    assert list(r["t"]) == [ts("2021-06-16 16:00"), ts("2021-06-16 18:00")] and list(r["tmin_end"]) == [1335, 120]
    assert r["c"][0] == 4 and r["o"][1] == 110                       # 16:14 closes the first bar, 18:00 opens the second
    # resolutions that used to fail to load
    for res, anchor in ((390, "09:30"), (50, "09:30")):
        bb = eng.load_bars(res, anchor)
        assert (np.diff(bb.t) > 0).all() and (bb.t_end[:-1] <= bb.t[1:]).all()


@test
def b06_a_signal_never_acts_on_its_own_bar():
    # a "signal" that knows its own bar's direction: if the engine filled at that bar's open (or anywhere inside it)
    # every trade would win.  Entered correctly at the next open the edge is gone.
    b = eng.load_bars(5)
    d = np.sign(b.c - b.o)
    rng = np.random.default_rng(2)
    d = np.where(rng.random(b.n) < 0.2, d, 0.0)
    r = eng.run(b, eng.Signals(d, max_bars=1))
    tr = r.trades
    e, sg = tr.entry_bar.to_numpy(), tr.signal_bar.to_numpy()
    assert len(tr) > 100000 and (e == sg + 1).all() and (tr.entry_price.to_numpy() == b.o[e]).all()
    cheat = np.abs(b.c[sg] - b.o[sg]).mean()            # what a same-bar fill would have earned per trade
    assert cheat > 3.0 and abs(tr.gross_pts.mean()) < 0.25, (cheat, tr.gross_pts.mean())
    # hand case: the signal bar closes far above its open; the fill is the NEXT open, which is all that matters
    bb = B([("10:00", 100, 110, 100, 110), ("10:05", 110, 110.5, 109.5, 110), ("10:10", 110, 110, 110, 110),
            ("10:15", 110, 110, 110, 110)])
    t1 = one_trade(eng.run(bb, eng.Signals(arr(bb.n, {0: 1}), max_bars=1)))
    assert t1.entry_price == 110.0 and close(t1.net_pts, -0.75)
    # stop / limit orders decided on bar i can not fill in bar i either, even if bar i traded there
    bb = B([("10:00", 100, 105, 95, 100), ("10:05", 100, 100.5, 99.5, 100), ("10:10", 100, 100.5, 99.5, 100)])
    for side, order, p in (("long", "stop", 104.0), ("long", "limit", 96.0), ("short", "stop", 96.0), ("short", "limit", 104.0)):
        r = eng.run(bb, eng.Signals(**{side: dict(entry=mask(bb.n, 0), order=order, price=arr(bb.n, fill=p))}))
        assert len(r.trades) == 0, (side, order)
    # the callback sees bar i only after it has closed, and its order acts from bar i+1
    def on_bar(ctx):
        if ctx.i == 0:
            ctx.buy_market()
    bb = B([("10:00", 100, 110, 100, 110), ("10:05", 110, 110.5, 109.5, 110), ("10:10", 110, 110, 110, 110)])
    assert one_trade(eng.run(bb, eng.Callback(on_bar))).entry_price == 110.0


def _strat_sma(bars, p):
    f, s = eng.sma(bars.c, p["fast"]), eng.sma(bars.c, p["slow"])
    up, dn = eng.cross_above(f, s), eng.cross_below(f, s)
    w = bars.time_between("09:35", "15:30")
    return eng.Signals(np.where(up & w, 1, np.where(dn & w, -1, 0)), stop_pts=eng.atr(bars.h, bars.l, bars.c, 14) * 2.0,
                       target_r=1.5, exit_long=dn, exit_short=up, exit_time="15:55")


def _strat_orb(bars, p):
    orh, orl = eng.opening_range(bars, "09:30", p["or_min"])
    go = (bars.tmin_end == eng.tmin_of("09:30") + p["or_min"]) & ~np.isnan(orh)
    go &= (orh - orl) <= p["w"] * eng.daily_atr(bars, 14)
    pr = eng.prior_rth(bars)
    return eng.Signals(long=dict(entry=go & (bars.c > pr["close"]), order="stop", price=orh + eng.TICK, stop=orl),
                       short=dict(entry=go & (bars.c < pr["close"]), order="stop", price=orl - eng.TICK, stop=orh),
                       target_r=2.0, last_entry="12:00", exit_time="15:55", max_trades_per_day=1, be_trigger_r=1.0)


def _strat_fade(bars, p):
    """Callback: fade stretched moves away from the time-weighted proxy with limit orders, overnight range filter."""
    tw, sd = eng.twap_vwap_proxy(bars, bands=True)
    a = eng.atr(bars.h, bars.l, bars.c, 14)
    onh, onl = eng.overnight_range(bars)
    g = eng.gap(bars)
    c, l, h = bars.c, bars.l, bars.h
    win = bars.time_between("10:00", "15:00")

    def on_bar(ctx):
        i = ctx.i
        if ctx.position == 0:
            if ctx.pending_long or ctx.pending_short or not win[i] or ctx.trades_today >= 2:
                return
            if sd[i] != sd[i] or a[i] != a[i] or g[i] != g[i]:
                return
            if c[i] < tw[i] - p["k"] * sd[i] and c[i] > onl[i]:
                ctx.buy_limit(l[i], stop_pts=2 * a[i], target=tw[i], expiry_bars=3)
            elif c[i] > tw[i] + p["k"] * sd[i] and c[i] < onh[i]:
                ctx.sell_limit(h[i], stop_pts=2 * a[i], target=tw[i], expiry_bars=3)
        elif ctx.bars_held >= 12:
            ctx.exit()
    return eng.Callback(on_bar, active=win, exit_time="15:55")


def _independent_truncation_check(fn, params, bars, cuts):
    """Run on the data and on truncated data; trades closed before the cut and entries before the cut must agree."""
    full = eng.run(bars, fn(bars, params)).trades
    cols = ["signal_bar", "entry_bar", "exit_bar", "direction", "entry_price", "exit_price", "exit_reason", "net_pts",
            "stop_price", "target_price", "mae_pts", "mfe_pts"]
    n_cmp = 0
    for k in cuts:
        part = eng.run(bars.truncate(k), fn(bars.truncate(k), params)).trades
        a = full[full.exit_bar < k - 1].reset_index(drop=True)
        b_ = part[part.exit_bar < k - 1].reset_index(drop=True)
        assert len(a) == len(b_), f"cut {k}: {len(a)} closed trades on the full data, {len(b_)} on the truncated data"
        for col in cols:
            x, y = a[col].to_numpy(), b_[col].to_numpy()
            ok = (x == y) if x.dtype.kind in "OUS" else eq_arr(x.astype(float), y.astype(float), 1e-9)
            assert ok if isinstance(ok, bool) else ok.all(), f"cut {k}: column {col} differs"
        ea = full[full.entry_bar < k][["signal_bar", "entry_bar", "direction", "entry_price"]].reset_index(drop=True)
        eb = part[part.entry_bar < k][["signal_bar", "entry_bar", "direction", "entry_price"]].reset_index(drop=True)
        assert len(ea) == len(eb) and eq_arr(ea.to_numpy(float), eb.to_numpy(float), 1e-9), f"cut {k}: entries differ"
        n_cmp += len(a)
    return n_cmp, len(full)


@test
def b07_no_lookahead_property_on_real_data_three_strategies():
    b = eng.load_bars(5)
    rng = np.random.default_rng(11)
    d = b.days
    cuts = set(int(x) for x in rng.integers(b.n // 10, b.n - 1, size=5))
    for j in rng.integers(300, len(d) - 1, size=4):          # inside the opening range, mid-session, last bar of a day
        r = d.iloc[int(j)]
        if r.rth_first >= 0:
            cuts |= {int(r.rth_first) + 3, int(r.rth_first) + 30, int(r["last"]) + 1}
    cuts = sorted(cuts)
    for name, fn, params in (("sma", _strat_sma, {"fast": 10, "slow": 40}), ("orb", _strat_orb, {"or_min": 30, "w": 0.6}),
                             ("fade", _strat_fade, {"k": 2.0})):
        n_cmp, n_full = _independent_truncation_check(fn, params, b, cuts)
        assert n_full > 500 and n_cmp > 500, (name, n_full, n_cmp)
        problems = eng.check_no_lookahead(fn, params, b, cuts=cuts[:6])
        assert problems == [], (name, problems[:2])
        assert eng.check_no_lookahead(fn, params, b) == [], name          # the default (first 500 days, random cuts)


@test
def b08_the_lookahead_check_catches_leaking_strategies():
    b = _slice(5, 0.5, 40000)

    def leak_day_high(bars, p):          # today's final regular-session high, known only after the close
        hi = bars.days["rth_high"].to_numpy()[bars.day_idx]
        return eng.Signals(long=dict(entry=bars.opens_at("10:00"), order="limit", price=hi - 50.0), max_bars=6)

    def leak_next_close(bars, p):        # the next bar's close, used once a day (clipped index)
        nxt = np.r_[bars.c[1:], bars.c[-1]]
        return eng.Signals(np.where(bars.opens_at("10:00"), np.sign(nxt - bars.c), 0), max_bars=1)

    def leak_roll(bars, p):              # np.roll wraps around
        nxt = np.roll(bars.c, -1)
        return eng.Signals(np.where(bars.opens_at("11:00") & (nxt > bars.c), 1, 0), max_bars=3)

    def leak_shift(bars, p):             # pandas shift(-1)
        nxt = pd.Series(bars.h).shift(-1).to_numpy()
        return eng.Signals(long=dict(entry=bars.opens_at("14:00") & (nxt > bars.h), order="stop", price=bars.h + 0.25), max_bars=3)

    def leak_exit(bars, p):              # honest entries, a sparse exit signal that knows the next bar
        nxt = np.r_[bars.c[1:], bars.c[-1]]
        ex = bars.time_between("10:30", "15:00") & (bars.mod % 30 == 0) & (nxt < bars.c - 3)
        return eng.Signals(np.where(bars.opens_at("10:00"), 1, 0), exit_long=ex)

    def leak_centered(bars, p):          # a centered moving average
        ma = pd.Series(bars.c).rolling(21, center=True, min_periods=1).mean().to_numpy()
        return eng.Signals(np.where(bars.opens_at("11:00"), np.sign(ma - bars.c), 0), max_bars=3)

    def leak_full_sample(bars, p):       # a threshold fitted on the whole sample
        z = (bars.c - bars.c.mean()) / bars.c.std()
        return eng.Signals(np.where(bars.opens_at("11:00") & (z > 0), 1, 0), max_bars=3)

    def leak_rth_last(bars, p):          # "the last regular-session bar of today" taken from the day table
        last = bars.days["rth_last"].to_numpy()[bars.day_idx]
        return eng.Signals(np.where(np.arange(bars.n) == last - 3, 1, 0), max_bars=2)

    def leak_callback(bars, p):          # a callback that reads two bars ahead
        c = bars.c

        def on_bar(ctx):
            i = ctx.i
            if ctx.position == 0 and i + 2 < bars.n and bars.mod[i] == 600 and c[i + 2] > c[i]:
                ctx.buy_market(max_bars=2)
        return eng.Callback(on_bar)

    def leak_cb_one_bar_market(bars, p):     # exactly one bar ahead, clipped index, market order
        c, go = bars.c, bars.opens_at("10:00")

        def on_bar(ctx):
            i = ctx.i
            if go[i] and ctx.position == 0 and c[min(i + 1, bars.n - 1)] > c[i]:
                ctx.buy_market(max_bars=1)
        return eng.Callback(on_bar)

    def leak_cb_one_bar_stop(bars, p):       # exactly one bar ahead, clipped index, stop orders only
        c, go = bars.c, bars.opens_at("10:00")

        def on_bar(ctx):
            i = ctx.i
            if go[i] and ctx.position == 0 and c[min(i + 1, bars.n - 1)] > c[i] + 2:
                ctx.buy_stop(bars.h[i] + 0.25, max_bars=2, expiry_bars=1)
        return eng.Callback(on_bar)

    def leak_cb_array(bars, p):              # a precomputed array that is one bar ahead, read in a callback
        nxt_ret = np.diff(bars.c, append=bars.c[-1])
        go = bars.opens_at("10:00") | bars.opens_at("13:00")

        def on_bar(ctx):
            i = ctx.i
            if go[i] and ctx.position == 0 and abs(nxt_ret[i]) > 2:
                (ctx.buy_market if nxt_ret[i] > 0 else ctx.sell_market)(max_bars=1)
        return eng.Callback(on_bar)

    def leak_cb_exit(bars, p):               # honest entries, the exit knows the next bar
        c, go = bars.c, bars.opens_at("10:00")

        def on_bar(ctx):
            i = ctx.i
            if go[i] and ctx.position == 0:
                ctx.buy_market()
            elif ctx.position != 0 and not ctx.exiting and c[min(i + 1, bars.n - 1)] < c[i] - 3:
                ctx.exit()
        return eng.Callback(on_bar)

    def leak_cb_stop(bars, p):               # honest entries, the stop is moved to just under the next bar's low
        lo, go = bars.l, bars.opens_at("10:00")

        def on_bar(ctx):
            i = ctx.i
            if go[i] and ctx.position == 0:
                ctx.buy_market(stop_pts=30.0, max_bars=12)
            elif ctx.position != 0:
                ns = lo[min(i + 1, bars.n - 1)] - 0.25
                if ns > ctx.stop:
                    ctx.set_stop(ns)
        return eng.Callback(on_bar)

    leaks = (leak_day_high, leak_next_close, leak_roll, leak_shift, leak_exit, leak_centered, leak_full_sample,
             leak_rth_last, leak_callback, leak_cb_one_bar_market, leak_cb_one_bar_stop, leak_cb_array, leak_cb_exit,
             leak_cb_stop)
    for fn in leaks:
        for seed in (0, 1, 2):
            problems = eng.check_no_lookahead(fn, {}, b, seed=seed)
            assert problems, f"{fn.__name__} (seed {seed}): lookahead not detected"
    # the one-bar leaks really pay: this is what a missed check would let through
    full = eng.load_bars(5)
    st = eng.stats(eng.run(full, leak_next_close(full, {})).trades)
    assert st["OOS"]["t_stat"] > 10 and st["IS"]["t_stat"] > 10

    # honest strategies of the same shapes are not flagged (several seeds = several sets of cuts)
    def ok_cb_reverse(bars, p):
        f, sl = eng.ema(bars.c, 10), eng.ema(bars.c, 50)
        win = bars.time_between("09:35", "15:30")

        def on_bar(ctx):
            i = ctx.i
            if not win[i] or f[i] != f[i] or sl[i] != sl[i]:
                return
            want = 1 if f[i] > sl[i] else -1
            if ctx.position == 0:
                if not (ctx.pending_long or ctx.pending_short):
                    (ctx.buy_market if want > 0 else ctx.sell_market)(stop_pts=20.0)
            elif ctx.position != want and not ctx.exiting:
                ctx.exit()
                (ctx.buy_market if want > 0 else ctx.sell_market)(stop_pts=20.0)
        return eng.Callback(on_bar, exit_time="15:55")

    def ok_cb_two_sided(bars, p):
        orh, orl = eng.opening_range(bars, "09:30", 15)
        go = bars.tmin_end == eng.tmin_of("09:45")

        def on_bar(ctx):
            i = ctx.i
            if i + 1 >= bars.n:                  # a callback may know how long the data is
                return
            if go[i] and orh[i] == orh[i] and ctx.position == 0:
                ctx.buy_stop(orh[i] + 0.25, stop=orl[i], target_r=1.5)
                ctx.sell_stop(orl[i] - 0.25, stop=orh[i], target_r=1.5)
            if ctx.position != 0 and ctx.mfe >= ctx.risk and (ctx.entry_price - ctx.stop) * ctx.position > 0:
                ctx.set_stop(ctx.entry_price)
            if ctx.position == 0 and (ctx.pending_long or ctx.pending_short) and bars.mod[i] >= 720:
                ctx.cancel()
        return eng.Callback(on_bar, max_trades_per_day=1, exit_time="15:55", last_entry="12:00")

    def ok_arr_sparse(bars, p):
        g, a = eng.gap(bars), eng.daily_atr(bars)
        go = bars.ends_at("09:35") & ~np.isnan(g) & ~np.isnan(a)
        return eng.Signals(np.where(go, -np.sign(g), 0), stop_pts=np.where(a > 0, a * 0.5, np.nan), target_r=1.0,
                           exit_time="12:00")

    for fn, params in ((ok_cb_reverse, {}), (ok_cb_two_sided, {}), (ok_arr_sparse, {}), (_strat_sma, {"fast": 10, "slow": 40}),
                       (_strat_orb, {"or_min": 30, "w": 0.6}), (_strat_fade, {"k": 2.0})):
        assert len(eng.run(b, fn(b, params)).trades) > 50, fn.__name__
        for seed in (0, 1, 2, 3):
            problems = eng.check_no_lookahead(fn, params, b, seed=seed)
            assert problems == [], f"{fn.__name__} (seed {seed}): false alarm: {problems[:1]}"
    # and the runner refuses to write a result for such a strategy
    with tempfile.TemporaryDirectory() as tmp:
        try:
            eng.run_config("leak", "leak", {}, leak_day_high, 5, out_dir=tmp, bars=b, verbose=False)
        except eng.LookaheadError:
            pass
        else:
            raise AssertionError("run_config accepted a strategy with lookahead")
        assert os.listdir(os.path.join(tmp, "results")) == [] and os.listdir(os.path.join(tmp, "trades")) == []
        # a clean strategy is written, and an existing file is not replaced
        out = eng.run_config("ok_sma", "sma", {"fast": 10, "slow": 40}, _strat_sma, 5, out_dir=tmp, bars=b, verbose=False)
        assert out["lookahead_check"] == "passed" and out["split_date"] == eng.SPLIT_DATE and out["tradeify_usable"] is True
        assert out["costs"] == {"tick": 0.25, "stop_order_slippage_pts": 0.25, "round_trip_cost_pts": 0.75}
        csv = pd.read_csv(os.path.join(tmp, "trades", "ok_sma.csv"))
        assert len(csv) == out["n_trades"] == out["stats"]["ALL"]["trades"] and close(csv.net_pts.sum(), out["stats"]["ALL"]["total_net_pts"], 1e-3)
        try:
            eng.run_config("ok_sma", "sma", {"fast": 10, "slow": 40}, _strat_sma, 5, out_dir=tmp, bars=b, verbose=False)
        except FileExistsError:
            pass
        else:
            raise AssertionError("an existing result file was replaced")


@test
def b09_indicator_inputs_with_gaps_are_documented_not_silent():
    # ema / wilder (and atr, rsi, adx, keltner built on them) are recursive: ENGINE.md must say what an interior NaN
    # does, because a level helper (gap, opening range, prior levels) fed into them has NaNs every day
    c = np.arange(1.0, 301.0)
    x = c.copy()
    x[100] = NAN
    e, w, s = eng.ema(x, 10), eng.wilder(x, 10), eng.sma(x, 10)
    assert not np.isnan(s[111:]).any()                         # the rolling mean recovers after the window has passed
    with open(os.path.join(os.path.dirname(os.path.abspath(eng.__file__)), "ENGINE.md")) as fh:
        doc = fh.read()
    if np.isnan(e[150:]).all() or np.isnan(w[150:]).all():
        assert "NaN" in doc and ("every later value" in doc or "all later values" in doc), \
            "ema/wilder turn NaN for good after one interior NaN and ENGINE.md does not say so"
    # leading NaNs are fine: the series starts at the first valid value
    y = np.r_[np.full(7, NAN), c]
    assert eq_arr(eng.ema(y, 10)[7:], eng.ema(c, 10)) and eq_arr(eng.wilder(y, 10)[7:], eng.wilder(c, 10))


# =====================================================================================================================
# C. STATISTICS
# =====================================================================================================================
def _fake_trades(net, days, risk=None, mae=None, minutes=None):
    n = len(net)
    d = pd.DatetimeIndex(pd.to_datetime(days))
    risk = np.full(n, NAN) if risk is None else np.asarray(risk, dtype="float64")
    net = np.asarray(net, dtype="float64")
    return pd.DataFrame({"net_pts": net, "gross_pts": net + 0.75, "entry_day": d, "r_multiple": net / risk,
                         "mae_pts": np.zeros(n) if mae is None else np.asarray(mae, dtype="float64"),
                         "minutes_held": np.full(n, 5.0) if minutes is None else np.asarray(minutes, dtype="float64"),
                         "split": np.where(d >= pd.Timestamp(eng.SPLIT_DATE), "OOS", "IS")})


@test
def c01_t_and_p_values_hand_computed_and_against_scipy():
    # five trades: mean 1, sample sd sqrt(10) -> t = 1 / (sqrt(10)/sqrt(5)) = 0.70710678..., df 4
    net = [3.0, -1.0, 4.0, -3.0, 2.0]
    tr = _fake_trades(net, ["2015-01-05", "2015-01-05", "2015-01-06", "2015-01-07", "2015-01-07"])
    st = eng.stats(tr)
    s = st["IS"]
    assert s["trades"] == 5 and close(s["mean_net_pts"], 1.0) and close(s["std_net_pts"], math.sqrt(8.5))
    t = 1.0 / (math.sqrt(8.5) / math.sqrt(5))
    assert close(s["t_stat"], t)
    ref = sps.ttest_1samp(net, 0.0, alternative="greater")
    assert close(s["t_stat"], ref.statistic) and close(s["p_one_sided"], ref.pvalue)
    assert close(s["p_one_sided"], 1 - sps.t.cdf(t, 4)) and 0.2 < s["p_one_sided"] < 0.3
    # a negative mean gives p > 0.5 (one-sided for mean > 0), never a "significant" loser
    s2 = eng.stats(_fake_trades([-x for x in net], ["2015-01-05"] * 5))["IS"]
    assert close(s2["p_one_sided"], 1 - s["p_one_sided"]) and s2["p_one_sided"] > 0.5 and close(s2["t_stat"], -t)
    # win rate, profit factor, totals
    assert close(s["win_rate"], 0.6) and close(s["profit_factor"], 9.0 / 4.0) and close(s["total_net_pts"], 5.0)
    assert close(s["mean_gross_pts"], 1.75)
    # max drawdown of the cumulative net (3, 2, 6, 3, 5): 3
    assert close(s["max_drawdown_pts"], 3.0)
    # the splits are disjoint and ALL is their union
    assert st["OOS"]["trades"] == 0 and st["ALL"]["trades"] == 5 and st["OOS"]["mean_net_pts"] is None and st["OOS"]["t_stat"] is None
    # degenerate inputs give None, not a number
    s1 = eng.stats(_fake_trades([2.0], ["2015-01-05"]))["IS"]
    assert s1["t_stat"] is None and s1["p_one_sided"] is None and s1["boot_ci95_mean"] is None and s1["profit_factor"] is None
    s0 = eng.stats(_fake_trades([1.0, 1.0, 1.0], ["2015-01-05"] * 3))["IS"]
    assert s0["t_stat"] is None and s0["p_one_sided"] is None
    # a large random sample against scipy
    rng = np.random.default_rng(0)
    x = rng.normal(0.05, 5.0, 5000)
    sx = eng.stats(_fake_trades(x, ["2015-01-05"] * 5000))["IS"]
    ref = sps.ttest_1samp(x, 0.0, alternative="greater")
    assert close(sx["t_stat"], ref.statistic, 1e-9) and close(sx["p_one_sided"], ref.pvalue, 1e-12)


@test
def c02_day_clustered_t_hand_computed():
    # day sums: 01-05: 3-1 = 2 ; 01-06: 4 ; 01-07: -3+2 = -1  -> mean 5/3, sd sqrt(((1/3)^2+(7/3)^2+(8/3)^2)/2)
    net = [3.0, -1.0, 4.0, -3.0, 2.0]
    s = eng.stats(_fake_trades(net, ["2015-01-05", "2015-01-05", "2015-01-06", "2015-01-07", "2015-01-07"]))["IS"]
    dm = 5.0 / 3.0
    dsd = math.sqrt(((2 - dm) ** 2 + (4 - dm) ** 2 + (-1 - dm) ** 2) / 2.0)
    assert s["days_traded"] == 3 and close(s["day_mean_net_pts"], dm) and close(s["day_std_net_pts"], dsd)
    assert close(s["day_t_stat"], dm / (dsd / math.sqrt(3))) and close(s["day_p_one_sided"], sps.t.sf(dm / (dsd / math.sqrt(3)), 2))
    assert close(s["worst_day_net_pts"], -1.0)
    # perfectly correlated trades inside a day: the per-trade t is inflated, the day t is not
    rng = np.random.default_rng(4)
    day_val = rng.normal(0.3, 2.0, 200)
    days = pd.bdate_range("2012-01-02", periods=200)
    net = np.repeat(day_val, 10)
    s = eng.stats(_fake_trades(net, np.repeat(days.values, 10)))["IS"]
    ref = sps.ttest_1samp(day_val * 10, 0.0, alternative="greater")
    assert s["days_traded"] == 200 and close(s["day_t_stat"], ref.statistic, 1e-9) and close(s["day_p_one_sided"], ref.pvalue, 1e-12)
    assert s["t_stat"] > 3.0 * s["day_t_stat"] > 0            # sqrt(10) times as large
    # trades of one trading day entered through the engine are grouped by ENTRY TRADING DAY (evening = next day)
    rows = [("2021-06-15 15:00", 100, 101, 99, 100), ("2021-06-15 15:05", 100, 101, 99, 101), ("2021-06-15 15:10", 101, 102, 100, 102),
            ("2021-06-15 16:10", 102, 103, 101, 102), ("2021-06-15 18:00", 102, 105, 101, 104), ("2021-06-15 18:05", 104, 105, 103, 104),
            ("2021-06-16 10:00", 104, 105, 103, 104), ("2021-06-16 10:05", 104, 108, 103, 107), ("2021-06-16 10:10", 107, 107, 107, 107)]
    b = B(rows)
    tr = eng.run(b, eng.Signals(arr(b.n, {0: 1, 3: 1, 6: 1}), max_bars=1)).trades
    assert list(tr.net_pts) == [0.25, 1.25, 2.25]
    s = eng.stats(tr)["OOS"]
    assert s["days_traded"] == 2 and close(s["day_mean_net_pts"], (0.25 + 3.5) / 2) and close(s["worst_day_net_pts"], 0.25)


@test
def c03_bootstrap_interval():
    rng = np.random.default_rng(7)
    x = rng.normal(0.4, 6.0, 3000)
    ci = eng.bootstrap_mean_ci(x)
    assert ci == eng.bootstrap_mean_ci(x)                              # fixed seed: the same every time
    assert eng.BOOT_RESAMPLES == 2000 and eng.BOOT_SEED == 12345
    se = x.std(ddof=1) / math.sqrt(len(x))
    assert ci[0] < x.mean() < ci[1]
    assert abs(ci[0] - (x.mean() - 1.96 * se)) < 0.2 * se and abs(ci[1] - (x.mean() + 1.96 * se)) < 0.2 * se
    # an independent percentile bootstrap with another generator agrees within Monte-Carlo error
    r2 = np.random.default_rng(999)
    means = np.array([x[r2.integers(0, len(x), len(x))].mean() for _ in range(2000)])
    lo, hi = np.percentile(means, [2.5, 97.5])
    assert abs(ci[0] - lo) < 0.15 * se and abs(ci[1] - hi) < 0.15 * se
    # the same draw order as one plain call of the documented generator (resamples are whole samples of size n)
    r3 = np.random.default_rng(eng.BOOT_SEED)
    m3 = x[r3.integers(0, len(x), size=(2000, len(x)))].mean(axis=1)
    lo3, hi3 = np.percentile(m3, [2.5, 97.5])
    assert close(ci[0], lo3, 1e-12) and close(ci[1], hi3, 1e-12)
    # skewed data: the percentile interval is not symmetric but still brackets the mean; it is what stats() reports
    y = rng.exponential(2.0, 400) - 1.0
    s = eng.stats(_fake_trades(y, ["2015-01-05"] * 400))["IS"]
    assert s["boot_ci95_mean"] == eng.bootstrap_mean_ci(y) and s["boot_ci95_mean"][0] < y.mean() < s["boot_ci95_mean"][1]
    assert eng.bootstrap_mean_ci([1.0]) is None
    # coverage: over 200 samples from a known mean the 95% interval holds the truth about 95% of the time
    hit = 0
    for k in range(200):
        zz = np.random.default_rng(1000 + k).normal(1.0, 3.0, 80)
        c_ = eng.bootstrap_mean_ci(zz, n_boot=400)
        hit += c_[0] <= 1.0 <= c_[1]
    assert 178 <= hit <= 198, hit


@test
def c04_r_multiples_mae_and_trades_per_year():
    net = [2.0, -1.0, 3.0, -2.0]
    risk = [4.0, 2.0, NAN, 1.0]
    tr = _fake_trades(net, ["2015-01-05", "2015-01-06", "2021-01-05", "2021-01-06"], risk=risk, mae=[1.0, 2.0, 3.0, 10.0],
                      minutes=[5, 10, 15, 100])
    st = eng.stats(tr)
    # R = net / risk: 0.5, -0.5, (none), -2.0
    assert st["ALL"]["trades_with_stop"] == 3 and close(st["ALL"]["mean_r"], (0.5 - 0.5 - 2.0) / 3)
    assert close(st["IS"]["mean_r"], 0.0) and close(st["OOS"]["mean_r"], -2.0) and st["OOS"]["trades_with_stop"] == 1
    assert close(st["ALL"]["mae_median_pts"], 2.5) and close(st["ALL"]["mae_p90_pts"], float(np.percentile([1, 2, 3, 10], 90)))
    assert close(st["ALL"]["median_minutes_held"], 12.5)
    # trades per year use the fixed calendar length of each period, whatever the trades are
    d0, d1, d2 = pd.Timestamp("2010-11-15"), pd.Timestamp("2020-03-18"), pd.Timestamp("2026-10-30") + pd.Timedelta(days=1)
    y_is, y_oos, y_all = (d1 - d0).days / 365.25, (d2 - d1).days / 365.25, (d2 - d0).days / 365.25
    assert close(st["IS"]["trades_per_year"], 2 / y_is) and close(st["OOS"]["trades_per_year"], 2 / y_oos)
    assert close(st["ALL"]["trades_per_year"], 4 / y_all)
    assert close(y_is, 3411 / 365.25) and close(y_oos, 2418 / 365.25) and close(y_is + y_oos, y_all)     # days counted by hand
    assert st["split_years"] == {"IS": y_is, "OOS": y_oos, "ALL": y_all}
    assert st["ALL"]["net_pts_by_year"] == {"2015": 1.0, "2021": 1.0} and st["ALL"]["trades_by_year"] == {"2015": 2, "2021": 2}
    # through the engine: R = net / (entry fill to initial stop), also after the stop was moved
    b = B([("10:00", 100, 100.5, 99.5, 100), ("10:05", 100, 100.5, 99.5, 100), ("10:10", 100, 106.5, 99.75, 106),
           ("10:15", 106, 106, 106, 106), ("10:20", 106, 106, 106, 106)])
    tr = one_trade(eng.run(b, eng.Signals(arr(b.n, {0: 1}), stop_pts=2.0, target_r=3.0)))
    assert tr.target_price == 106.0 and tr.exit_reason == "target" and close(tr.risk_pts, 2.0) and close(tr.r_multiple, (6.0 - 0.75) / 2.0)
    # the split of the engine's trade rows and of stats() is the same constant
    assert st["split_date"] == eng.SPLIT_DATE and st["is_fraction"] == 0.6


@test
def c05_stats_of_a_real_run_recomputed_from_the_trades_table():
    b = eng.load_bars(5)
    tr = eng.run(b, _strat_orb(b, {"or_min": 30, "w": 0.6})).trades
    st = eng.stats(tr)
    assert len(tr) > 1500
    for name, sub in (("IS", tr[tr.entry_day < "2020-03-18"]), ("OOS", tr[tr.entry_day >= "2020-03-18"]), ("ALL", tr)):
        s = st[name]
        x = sub.net_pts.to_numpy()
        ref = sps.ttest_1samp(x, 0.0, alternative="greater")
        assert s["trades"] == len(sub) and close(s["mean_net_pts"], x.mean()) and close(s["t_stat"], ref.statistic, 1e-9)
        assert close(s["p_one_sided"], ref.pvalue, 1e-12)
        daily = sub.groupby(sub.entry_day.dt.strftime("%Y-%m-%d")).net_pts.sum().to_numpy()
        ref = sps.ttest_1samp(daily, 0.0, alternative="greater")
        assert s["days_traded"] == len(daily) and close(s["day_t_stat"], ref.statistic, 1e-9) and close(s["day_p_one_sided"], ref.pvalue, 1e-12)
        r = (sub.net_pts / sub.risk_pts).to_numpy()
        assert close(s["mean_r"], r[np.isfinite(r)].mean()) and close(s["win_rate"], (x > 0).mean())
        assert close(s["profit_factor"], x[x > 0].sum() / -x[x < 0].sum())
        assert s["boot_ci95_mean"][0] < x.mean() < s["boot_ci95_mean"][1]
        by_year = sub.groupby(sub.entry_day.dt.year).net_pts.sum()
        assert all(close(s["net_pts_by_year"][str(y)], v, 1e-6) for y, v in by_year.items())
    assert st["IS"]["trades"] + st["OOS"]["trades"] == st["ALL"]["trades"]
    assert (tr.split == np.where(tr.entry_day >= "2020-03-18", "OOS", "IS")).all()
    assert np.allclose(tr.net_pts, tr.gross_pts - 0.75) and np.allclose(tr.r_multiple, tr.net_pts / tr.risk_pts)
    assert (tr.mae_pts >= 0).all() and (tr.mfe_pts >= 0).all()
    # a stopped trade lost at least its risk plus the exit tick and the cost; MAE of a stop exit is at least the risk
    stp = tr[(tr.exit_reason == "stop") & ~tr.partial_exit & (tr.stop_price == tr.stop_price)]
    moved = eng.run(b, _strat_orb(b, {"or_min": 30, "w": 0.6})).rules.be_trigger_r is not None
    assert moved and (stp.net_pts <= 0.0 + 1e-9).all()


# =====================================================================================================================
# D. SANITY STRATEGIES ON THE REAL 5-MINUTE DATA
# =====================================================================================================================
@test
def d01_random_entries_average_minus_the_cost():
    b = eng.load_bars(5)
    n = b.n
    zs = []
    for hold, p, seed in ((1, 0.30, 100), (3, 0.20, 101), (6, 0.10, 102), (12, 0.05, 103), (24, 0.03, 104)):
        rng = np.random.default_rng(seed)
        d = np.where(rng.random(n) < p, rng.choice([-1, 1], size=n), 0)
        r = eng.run(b, eng.Signals(d, max_bars=hold))
        tr = r.trades
        g = tr.gross_pts.to_numpy()
        e, x, s = tr.entry_bar.to_numpy(), tr.exit_bar.to_numpy(), tr.direction.to_numpy()
        # every trade is exactly: next open -> close of the bar `hold` bars later (or the end of the day), minus 0.75
        assert np.array_equal(e, tr.signal_bar.to_numpy() + 1)
        assert np.allclose(g, s * (b.c[x] - b.o[e])) and np.allclose(tr.net_pts, g - 0.75) and (tr.slippage_pts == 0).all()
        by_bars = (tr.exit_reason == "bars").to_numpy()
        assert (x[by_bars] - e[by_bars] == hold - 1).all() and set(tr.exit_reason) <= {"bars", "eod"}
        assert abs((s > 0).mean() - 0.5) < 0.01
        se = g.std(ddof=1) / math.sqrt(len(g))
        z = g.mean() / se
        zs.append(z)
        st = eng.stats(tr)["ALL"]
        assert len(g) > 10000, (hold, len(g))
        assert abs(z) < 3.5, f"hold {hold}: mean gross {g.mean():.4f} is {z:.2f} standard errors from 0"
        assert abs(st["mean_net_pts"] - (-0.75)) < 3.5 * se and close(st["mean_net_pts"], g.mean() - 0.75)
        # the engine's own interval and p-value agree: a random strategy is not "significant"
        lo, hi = st["boot_ci95_mean"]
        assert lo - 2 * se < -0.75 < hi + 2 * se and st["p_one_sided"] > 0.5
    assert abs(np.mean(zs)) < 2.0, zs
    # the same with random stop and limit entry orders around the close and a fixed holding period: the exact P&L of
    # each trade is fill -> close, and the long/short mix is random, so the mean is - (0.75 + slippage) within error
    rng = np.random.default_rng(55)
    a = np.nan_to_num(eng.atr(b.h, b.l, b.c, 14), nan=5.0)
    sig = rng.random(n) < 0.05
    side = rng.choice([-1, 1], size=n)
    typ = rng.integers(1, 3, size=n)
    off = np.round(rng.uniform(0.1, 0.6, n) * a * 4) / 4
    price = np.where(typ == eng.STOP, b.c + side * off, b.c - side * off)
    r = eng.run(b, eng.Signals(long=dict(entry=sig & (side > 0), order=typ, price=price),
                               short=dict(entry=sig & (side < 0), order=typ, price=price), max_bars=6, expiry_bars=3))
    tr = r.trades
    e, x, s = tr.entry_bar.to_numpy(), tr.exit_bar.to_numpy(), tr.direction.to_numpy()
    is_stop = (tr.order_type == "stop").to_numpy()
    assert is_stop.sum() > 5000 and (~is_stop).sum() > 5000
    raw = tr.entry_price.to_numpy() - np.where(is_stop, s * 0.25, 0.0)
    assert ((raw >= b.l[e] - 1e-9) & (raw <= b.h[e] + 1e-9)).all()
    assert np.allclose(tr.gross_pts, s * (b.c[x] - tr.entry_price.to_numpy()))
    assert np.allclose(tr.slippage_pts, np.where(is_stop, 0.25, 0.0))


@test
def d02_buy_0930_sell_1600_matches_the_bars():
    b = eng.load_bars(5)
    r = eng.run(b, eng.Signals(b.ends_at("09:30").astype(int), exit_time="16:00", last_entry="09:30"))
    tr = r.trades
    # directly from the files, without the engine's Bars
    with np.load(eng.FILE_5M) as z5:
        t5, o5, c5 = z5["t"], z5["o"], z5["c"]
    loc5 = pd.DatetimeIndex(t5.astype("datetime64[s]"), tz="UTC").tz_convert("America/New_York").tz_localize(None)
    sec5 = loc5.values.astype("datetime64[s]").astype("int64")
    df = pd.DataFrame({"day": (sec5 // 86400).astype("datetime64[D]").astype(str), "mod": (sec5 % 86400) // 60, "o": o5, "c": c5})
    z1 = raw_1m()
    mod1, day1 = z1["mod"], z1["day"].astype(str)
    complete = set(complete_days_1m())
    op = df[df["mod"] == 570].set_index("day")["o"]
    cl = df[df["mod"] == 955].set_index("day")["c"]
    pre = set(df[df["mod"] == 565]["day"])                  # the 09:25 bar, after whose close the order is given
    days = [d for d in op.index if d in complete and d in cl.index and d in pre]
    direct = {d: float(cl[d] - op[d]) - 0.75 for d in days}
    got = dict(zip(tr.entry_day.dt.strftime("%Y-%m-%d"), tr.net_pts))
    assert len(tr) == len(got) == len(direct) == 3825, (len(tr), len(direct))
    assert set(got) == set(direct)
    assert max(abs(got[d] - direct[d]) for d in direct) < 1e-9
    total = sum(float(cl[d] - op[d]) for d in days)
    assert close(tr.net_pts.sum(), total - 0.75 * len(days), 1e-6) and close(tr.gross_pts.sum(), total, 1e-6)
    assert (tr.exit_reason == "time").all() and (tr.slippage_pts == 0).all()
    assert (tr.entry_time.dt.strftime("%H:%M") == "09:30").all() and (tr.exit_time.dt.strftime("%H:%M") == "16:00").all()
    # the same open-to-close moves from the 1-minute file (09:30 open, 15:59 close)
    d1 = pd.DataFrame({"day": day1, "mod": mod1, "o": z1["o"], "c": z1["c"]})
    op1 = d1[d1["mod"] == 570].set_index("day")["o"]
    cl1 = d1[d1["mod"] == 959].set_index("day")["c"]
    both = [d for d in days if d in op1.index and d in cl1.index]
    assert len(both) > 3800 and close(sum(float(cl1[d] - op1[d]) for d in both), sum(float(cl[d] - op[d]) for d in both), 1e-6)
    # statistics of this known strategy, recomputed
    st = eng.stats(tr)
    is_days = [d for d in days if d < "2020-03-18"]
    assert st["IS"]["trades"] == len(is_days) and close(st["IS"]["total_net_pts"], sum(direct[d] for d in is_days), 1e-6)
    assert st["IS"]["days_traded"] == st["IS"]["trades"] and close(st["IS"]["t_stat"], st["IS"]["day_t_stat"])
    # the mirror image: sell at 09:30, buy back at 16:00
    rs = eng.run(b, eng.Signals(-b.ends_at("09:30").astype(int), exit_time="16:00", last_entry="09:30")).trades
    assert close(rs.net_pts.sum(), -total - 0.75 * len(days), 1e-6)


@test
def d03_session_invariants_on_real_data():
    def strat(b, seed, le, multi, mt, xt):
        rng = np.random.default_rng(seed)
        n = b.n
        a = np.nan_to_num(eng.atr(b.h, b.l, b.c, 14), nan=5.0)

        def side(s):
            return dict(entry=rng.random(n) < 0.03, order=rng.integers(0, 3, n),
                        price=np.round((b.c + s * rng.normal(0, 0.5, n) * a) * 4) / 4,
                        stop_pts=np.maximum(np.round(a * rng.uniform(0.3, 3, n) * 4) / 4, 0.25))
        return eng.Signals(long=side(1), short=side(-1), target_r=1.5, last_entry=le, allow_multi_day=multi,
                           max_trades_per_day=mt, exit_time=xt)

    for res, anchor in ((5, "00:00"), (1, "00:00"), (15, "00:00"), (30, "00:00"), (60, "09:30"), (65, "09:30")):
        b = eng.load_bars(res, anchor)
        for le, multi, mt, xt in (("15:55", False, None, None), ("16:10", False, 2, "15:30"), (None, True, None, None)):
            r = eng.run(b, strat(b, 7, le, multi, mt, xt))
            tr = r.trades
            tag = f"{res}m {le} multi={multi}"
            e, x, sg, s = (tr[k].to_numpy() for k in ("entry_bar", "exit_bar", "signal_bar", "direction"))
            typ, reason = tr.order_type.to_numpy(), tr.exit_reason.to_numpy()
            assert len(tr) > 1000, tag
            assert not b.incomplete[e].any(), tag + ": entry on an incomplete day"
            assert (sg < e).all() and (e[typ == "market"] == sg[typ == "market"] + 1).all(), tag
            le_t = 9999 if le is None else eng.tmin_of(le)
            mk = typ == "market"
            assert (b.tmin[e[mk]] <= le_t).all() and (b.tmin_end[e[~mk]] <= le_t).all(), tag + ": entry after last_entry"
            assert ((e[1:] > x[:-1]) | ((e[1:] == x[:-1]) & (reason[:-1] == "signal"))).all(), tag + ": overlapping trades"
            assert np.allclose(tr.net_pts, tr.gross_pts - 0.75), tag
            raw_e = tr.entry_price.to_numpy() - np.where(typ == "stop", s * 0.25, 0.0)
            assert ((raw_e >= b.l[e] - 1e-9) & (raw_e <= b.h[e] + 1e-9)).all(), tag + ": entry fill outside the bar"
            assert (tr.entry_price.to_numpy()[mk] == b.o[e[mk]]).all(), tag
            raw_x = tr.exit_price.to_numpy() + np.where(reason == "stop", s * 0.25, 0.0)
            inside = (raw_x >= b.l[x] - 1e-9) & (raw_x <= b.h[x] + 1e-9)
            gap_t = (reason == "target") & (((s > 0) & (b.l[x] > raw_x)) | ((s < 0) & (b.h[x] < raw_x)))
            assert (inside | gap_t).all(), tag + ": exit fill outside the bar"
            tg = reason == "target"
            tp = tr.target_price.to_numpy()
            assert (tr.exit_price.to_numpy()[tg] == tp[tg]).all(), tag
            assert np.where(s[tg] > 0, b.h[x[tg]] > tp[tg], b.l[x[tg]] < tp[tg]).all(), tag + ": target not traded through"
            # no fill ever gets a better price than the bar offers: a long never exits above the high, etc.
            sp_ = reason == "stop"
            sx = tr.stop_price.to_numpy()
            worse = np.where(s[sp_] > 0, raw_x[sp_] <= np.minimum(sx[sp_], np.where(x[sp_] > e[sp_], b.o[x[sp_]], np.inf)) + 1e-9,
                             raw_x[sp_] >= np.maximum(sx[sp_], np.where(x[sp_] > e[sp_], b.o[x[sp_]], -np.inf)) - 1e-9)
            assert worse.all(), tag + ": a stop exit better than min(stop, open)"
            if not multi:
                assert (b.tday_id[e] == b.tday_id[x]).all(), tag + ": position held across trading days"
                assert (b.tmin_end[x] <= 1330).all(), tag + ": exit after 16:10"
                same = b.tday_id[sg] == b.tday_id[e]
                assert (same | (b.tmin_end[sg] == 1335)).all(), tag + ": order carried across days"
                ed = reason == "eod"
                xi = x[ed]
                nb = np.minimum(xi + 1, b.n - 1)
                assert ((xi == b.n - 1) | (b.tday_id[nb] != b.tday_id[xi]) | (b.tmin_end[nb] > 1330)).all(), tag
                assert (tr.exit_price.to_numpy()[ed] == b.c[xi]).all(), tag
                assert r.tradeify_usable is True
            else:
                assert r.tradeify_usable is False and (b.tday_id[e] != b.tday_id[x]).any(), tag
            if mt is not None:
                assert int(pd.Series(b.tday_id[e]).value_counts().max()) <= mt, tag
            t_out = tr.exit_time.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy().astype("datetime64[s]").astype("int64")
            t_in = tr.entry_time.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy().astype("datetime64[s]").astype("int64")
            assert (t_out == np.where(reason == "signal", b.t[x], b.t_end[x])).all() and (t_in == b.t[e]).all(), tag
            assert (t_out > t_in).all() and (tr.minutes_held > 0).all(), tag
            assert (tr.split == np.where(b.tday[e] >= np.datetime64(eng.SPLIT_DATE), "OOS", "IS")).all(), tag


# =====================================================================================================================
# E. AN INDEPENDENT PLAIN SIMULATOR AGAINST THE ENGINE
# =====================================================================================================================
def _ny_fields(t):
    out = []
    for x in t:
        d = datetime.fromtimestamp(int(x), tz=timezone.utc).astimezone(NYZ)
        mod = d.hour * 60 + d.minute
        out.append((d.date().toordinal() + (1 if mod >= 1080 else 0), (mod - 1080) % 1440))
    return out


def _ref_run(t, o, h, l, c, res, signals, *, incomplete, last_entry, exit_time, max_bars, max_trades_per_day, multi_day):
    """One-sided orders, written from ENGINE.md sections 6 to 8.  signals: bar -> dict(side, typ, price, stop,
    stop_pts, target, target_pts, expiry_bars)."""
    n = len(t)
    f = _ny_fields(t)
    day = [x[0] for x in f]
    tmin = [x[1] for x in f]
    tend = [min(a + res, 1335) for a in tmin]
    le = None if last_entry is None else (last_entry - 1080) % 1440
    xt = None if exit_time is None else (exit_time - 1080) % 1440
    hold = [True] * n if multi_day else [e <= 1330 for e in tend]

    def last_of_day(pred, j):
        if not pred(j):
            return False
        k = j + 1
        while k < n and day[k] == day[j]:
            if pred(k):
                return False
            k += 1
        return True

    trades = []
    pos, pend, cur_day, n_today = 0, None, None, 0
    for j in range(n):
        entered, raw = False, None
        if pos == 0 and pend is not None:
            od = pend
            sb = od["sig"]
            if od["typ"] == "market":
                alive = j == sb + 1
            else:
                alive = not (od.get("expiry_bars") is not None and j > sb + od["expiry_bars"])
                if (not multi_day or od.get("expiry_bars") is None) and day[j] != day[sb + 1]:
                    alive = False
            if not alive:
                pend = None
            else:
                if day[j] != cur_day:
                    cur_day, n_today = day[j], 0
                ok = (not incomplete[j]) and hold[j]
                ok = ok and (le is None or (tmin[j] <= le if od["typ"] == "market" else tend[j] <= le))
                if max_trades_per_day is not None and n_today >= max_trades_per_day:
                    ok = False
                s, p = od["side"], od.get("price")
                if ok:
                    if od["typ"] == "market":
                        raw = entry = o[j]
                    elif od["typ"] == "stop":
                        if s > 0 and h[j] >= p:
                            raw = max(p, o[j])
                            entry = raw + 0.25
                        elif s < 0 and l[j] <= p:
                            raw = min(p, o[j])
                            entry = raw - 0.25
                    elif s > 0 and l[j] < p:
                        raw = entry = min(p, o[j])
                    elif s < 0 and h[j] > p:
                        raw = entry = max(p, o[j])
                if raw is not None:
                    pos, entered, ebar, etyp, sig_of = s, True, j, od["typ"], sb
                    stop = od.get("stop")
                    if stop is None and od.get("stop_pts") is not None:
                        stop = entry - s * od["stop_pts"]
                    tgt = od.get("target")
                    if tgt is None and od.get("target_pts") is not None:
                        tgt = entry + s * od["target_pts"]
                    n_today += 1
                    pend = None
                elif od["typ"] == "market":
                    pend = None
        if pos != 0:
            s = pos
            exit_px = reason = None
            adverse = l[j] if s > 0 else h[j]
            favour = h[j] if s > 0 else l[j]
            ref = raw if entered else o[j]
            full = (not entered) or etyp == "market"
            if stop is not None and (adverse - stop) * s <= 0:
                px = stop if (stop - ref) * s < 0 else ref
                exit_px, reason = px - s * 0.25, "stop"
            elif full and tgt is not None and (favour - tgt) * s > 0:
                exit_px, reason = tgt, "target"
            if exit_px is None:
                if xt is not None and last_of_day(lambda k: tend[k] <= xt, j):
                    exit_px, reason = c[j], "time"
                elif max_bars is not None and j - ebar + 1 >= max_bars:
                    exit_px, reason = c[j], "bars"
                elif (not multi_day) and last_of_day(lambda k: hold[k], j):
                    exit_px, reason = c[j], "eod"
                elif j == n - 1:
                    exit_px, reason = c[j], "end_of_data"
            if exit_px is not None:
                trades.append((sig_of, ebar, j, s, entry, exit_px, reason, s * (exit_px - entry) - 0.75))
                pos = 0
        if pos == 0 and j in signals and j + 1 < n:
            if not ((not multi_day) and day[j + 1] != day[j] and tend[j] < 1335):
                pend = dict(signals[j], sig=j)
    return trades


def _random_days(rng, dates, res, drop, vol):
    t = []
    for y, m, d in dates:
        prev = datetime(y, m, d) - pd.Timedelta(days=1)
        k = 0
        while True:
            mins = 18 * 60 + k * res
            dd = prev if mins < 1440 else datetime(y, m, d)
            mm = mins % 1440
            if mins >= 1440 and mm >= 16 * 60 + 15:
                break
            t.append(int(datetime(dd.year, dd.month, dd.day, mm // 60, mm % 60, tzinfo=NYZ).timestamp()))
            k += 1
    t = np.array(t, dtype="int64")
    t = t[rng.random(len(t)) > drop]
    n = len(t)
    c = 1000 + np.cumsum(rng.integers(-vol, vol + 1, size=n)) * 0.25
    o = np.r_[1000.0, c[:-1]] + rng.integers(-1, 2, size=n) * 0.25 * (rng.random(n) < 0.3)
    hi = np.maximum(o, c) + rng.integers(0, 3, size=n) * 0.25
    lo = np.minimum(o, c) - rng.integers(0, 3, size=n) * 0.25
    return t, o, hi, lo, c


@test
def e01_engine_equals_an_independent_plain_simulator_on_random_bars():
    n_trades = 0
    reasons = set()
    for seed in range(160):
        rng = np.random.default_rng(seed)
        # the week of the spring DST change 2021 and a Friday -> Monday step
        dates = [(2021, 3, 9), (2021, 3, 10), (2021, 3, 11), (2021, 3, 12), (2021, 3, 15), (2021, 3, 16)]
        res = int(rng.choice([1, 5, 5, 5, 15]))
        if res == 1:
            dates = dates[2:5]
        t, o, h, l, c = _random_days(rng, dates, res, float(rng.choice([0, 0.02, 0.1])), int(rng.choice([1, 3, 6])))
        n = len(t)
        days = np.array([x[0] for x in _ny_fields(t)])
        inc = (days == rng.choice(np.unique(days))) if rng.random() < 0.5 else np.zeros(n, dtype=bool)
        bars = eng.Bars(t, o, h, l, c, res, incomplete=inc)
        side = int(rng.choice([1, -1]))
        sig = rng.random(n) < float(rng.choice([0.02, 0.1, 0.4]))
        typ = rng.integers(0, 3, size=n)
        price = c + rng.integers(-4, 5, size=n) * 0.25
        stop_mode, tgt_mode = rng.choice(["none", "price", "pts"]), rng.choice(["none", "price", "pts"])
        sd, td = rng.integers(1, 9, size=n) * 0.25, rng.integers(1, 9, size=n) * 0.25
        stop_arr, tgt_arr = price - side * sd, price + side * td
        if rng.random() < 0.3:                                    # sometimes a stop on the wrong side
            stop_arr = np.where(rng.random(n) < 0.1, price + side * sd, stop_arr)
        eb = None if rng.random() < 0.5 else int(rng.integers(1, 6))
        sig_d = {}
        for i in np.flatnonzero(sig):
            d = dict(side=side, typ=("market", "stop", "limit")[typ[i]], price=float(price[i]), expiry_bars=eb)
            if stop_mode == "price":
                d["stop"] = float(stop_arr[i])
            if stop_mode == "pts":
                d["stop_pts"] = float(sd[i])
            if tgt_mode == "price":
                d["target"] = float(tgt_arr[i])
            if tgt_mode == "pts":
                d["target_pts"] = float(td[i])
            sig_d[int(i)] = d
        kw = dict(entry=sig, order=typ, price=price)
        if stop_mode == "price":
            kw["stop"] = stop_arr
        if stop_mode == "pts":
            kw["stop_pts"] = sd
        if tgt_mode == "price":
            kw["target"] = tgt_arr
        if tgt_mode == "pts":
            kw["target_pts"] = td
        if eb is not None:
            kw["expiry_bars"] = eb
        le = rng.choice(["15:55", "15:55", "11:00", "16:05", None, "20:00"])
        xt = rng.choice([None, None, "15:00", "10:30", "16:00", "16:10", "03:00"])
        mb = None if rng.random() < 0.6 else int(rng.integers(1, 30))
        mt = None if rng.random() < 0.6 else int(rng.integers(1, 4))
        multi = bool(rng.random() < 0.25)
        S = eng.Signals(**({"long": kw} if side > 0 else {"short": kw}), last_entry=le, exit_time=xt, max_bars=mb,
                        max_trades_per_day=mt, allow_multi_day=multi)
        tr = eng.run(bars, S).trades
        hm_ = lambda s: None if s is None else int(s[:2]) * 60 + int(s[3:])
        ref = _ref_run(t, o, h, l, c, res, sig_d, incomplete=inc, last_entry=hm_(le), exit_time=hm_(xt), max_bars=mb,
                       max_trades_per_day=mt, multi_day=multi)
        tag = f"seed {seed} res {res} side {side} stop {stop_mode} target {tgt_mode} expiry {eb} last {le} exit {xt} " \
              f"max_bars {mb} max/day {mt} multi {multi}"
        assert len(tr) == len(ref), f"{tag}: {len(tr)} engine trades, {len(ref)} reference trades"
        got = list(zip(tr.signal_bar, tr.entry_bar, tr.exit_bar, tr.direction, tr.entry_price, tr.exit_price, tr.exit_reason,
                       tr.net_pts))
        for k, (g, e) in enumerate(zip(got, ref)):
            assert g[:4] == e[:4] and g[6] == e[6] and close(g[4], e[4]) and close(g[5], e[5]) and close(g[7], e[7]), \
                f"{tag}: trade {k}: engine {g} reference {e}"
        n_trades += len(ref)
        reasons |= set(tr.exit_reason)
    assert n_trades > 5000 and reasons == {"stop", "target", "time", "bars", "eod", "end_of_data"}, (n_trades, reasons)


@test
def e02_long_and_short_are_mirror_images():
    K = 3000.0
    n_tr = 0
    for seed in range(120):
        rng = np.random.default_rng(seed)
        dates = [(2021, 11, 3), (2021, 11, 4), (2021, 11, 5), (2021, 11, 8), (2021, 11, 9)]     # across the fall DST change
        t, o, h, l, c = _random_days(rng, dates, 5, float(rng.choice([0, 0.03])), int(rng.choice([1, 3, 6])))
        n = len(t)
        bars = eng.Bars(t, o, h, l, c, 5)
        mbars = eng.Bars(t, K - o, K - l, K - h, K - c, 5)
        d = dict(entry=rng.random(n) < float(rng.choice([0.03, 0.15])), order=rng.integers(0, 3, size=n),
                 price=c + rng.integers(-4, 5, size=n) * 0.25)
        sd = rng.integers(1, 9, size=n) * 0.25
        d["stop"] = d["price"] - sd
        td = rng.integers(2, 12, size=n) * 0.25
        tm = rng.choice(["price", "pts", "r"])
        if tm == "price":
            d["target"] = d["price"] + td
        elif tm == "pts":
            d["target_pts"] = td
        else:
            d["target_r"] = 2.0
        if rng.random() < 0.5:
            d["tp1_r"] = 0.5
        if rng.random() < 0.3:
            d["exit"] = rng.random(n) < 0.05
        if rng.random() < 0.3:
            d["trail"] = c - rng.integers(2, 10, size=n) * 0.25
        m = dict(d)
        for k in ("price", "stop", "target", "trail"):
            if k in m:
                m[k] = K - m[k]
        run_kw = dict(exit_time=rng.choice([None, "15:00"]), tp1_frac=float(rng.choice([0.5, 0.25])),
                      max_trades_per_day=None if rng.random() < 0.5 else 3)
        if rng.random() < 0.4:
            run_kw["be_trigger_pts"] = float(rng.integers(2, 8) * 0.25)
        if rng.random() < 0.4:
            run_kw["trail_pts"] = float(rng.integers(2, 10) * 0.25)
        a = eng.run(bars, eng.Signals(long=d, **run_kw)).trades
        b_ = eng.run(mbars, eng.Signals(short=m, **run_kw)).trades
        assert len(a) == len(b_), seed
        for col in ("signal_bar", "entry_bar", "exit_bar", "net_pts", "gross_pts", "mae_pts", "mfe_pts", "risk_pts",
                    "slippage_pts", "bars_held", "partial_frac"):
            assert eq_arr(a[col].to_numpy(float), b_[col].to_numpy(float), 1e-9), (seed, col)
        for col in ("entry_price", "exit_price", "stop_price", "target_price", "partial_price"):
            assert eq_arr(a[col].to_numpy(float), K - b_[col].to_numpy(float), 1e-9), (seed, col)
        assert (a.direction.to_numpy() == -b_.direction.to_numpy()).all() and list(a.exit_reason) == list(b_.exit_reason)
        n_tr += len(a)
    assert n_tr > 2500, n_tr


@test
def e03_array_path_and_callback_path_give_the_same_trades():
    b = _slice(5, 0.7, 60000)
    rng = np.random.default_rng(21)
    n = b.n
    a = np.nan_to_num(eng.atr(b.h, b.l, b.c, 14), nan=5.0)
    sig = rng.random(n) < 0.05
    side = rng.choice([-1, 1], size=n)
    typ = rng.integers(0, 3, size=n)
    price = np.round((b.c + rng.normal(0, 0.4, n) * a) * 4) / 4
    stop_pts = np.maximum(np.round(a * 1.5 * 4) / 4, 0.25)
    S = eng.Signals(long=dict(entry=sig & (side > 0), order=typ, price=price),
                    short=dict(entry=sig & (side < 0), order=typ, price=price),
                    stop_pts=stop_pts, target_r=1.5, expiry_bars=4, exit_time="15:30", max_trades_per_day=3)
    ra = eng.run(b, S).trades

    def on_bar(ctx):
        i = ctx.i
        if ctx.position == 0 and sig[i]:
            kw = dict(stop_pts=stop_pts[i], target_r=1.5, expiry_bars=4)
            ctx.order(int(side[i]), int(typ[i]), price[i], **kw)
    rb = eng.run(b, eng.Callback(on_bar, exit_time="15:30", max_trades_per_day=3)).trades
    assert len(ra) == len(rb) > 500
    for col in ("signal_bar", "entry_bar", "exit_bar", "direction", "entry_price", "exit_price", "net_pts", "mae_pts", "mfe_pts"):
        assert eq_arr(ra[col].to_numpy(float), rb[col].to_numpy(float), 1e-9), col
    assert list(ra.exit_reason) == list(rb.exit_reason) and list(ra.order_type) == list(rb.order_type)


# =====================================================================================================================
def main():
    warnings.simplefilter("error")
    only = sys.argv[1:]
    passed, failed = 0, []
    t_all = time.perf_counter()
    for fn in TESTS:
        if only and not any(k in fn.__name__ for k in only):
            continue
        t0 = time.perf_counter()
        try:
            fn()
        except Exception:
            failed.append(fn.__name__)
            print(f"FAIL  {fn.__name__}  ({time.perf_counter() - t0:.1f}s)")
            traceback.print_exc()
        else:
            passed += 1
            print(f"ok    {fn.__name__}  ({time.perf_counter() - t0:.1f}s)")
    total = passed + len(failed)
    print(f"\n{passed} of {total} review tests passed in {time.perf_counter() - t_all:.0f}s"
          + (f"; FAILED: {', '.join(failed)}" if failed else ""))
    print(f"engine {eng.ENGINE_VERSION}  sha256 {eng.ENGINE_SHA256[:16]}  split {eng.SPLIT_DATE}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
