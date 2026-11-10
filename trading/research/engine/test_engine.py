#!/usr/bin/env python3
"""Unit tests of engine.py.  Run:  python3 -I test_engine.py   (add -v for one line per test)

Small hand-built bars with hand-computed expected results for every fill, cost and session rule; independent pandas /
loop references for every indicator; and checks on the real data (split, resampling, DST, no lookahead, run time).
"""
import json
import math
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
from scipy import stats as sps

import engine as E

NYZ = ZoneInfo("America/New_York")
HAVE_DATA = os.path.exists(E.FILE_1M) and os.path.exists(E.FILE_5M)
NAN = float("nan")


# ---------------------------------------------------------------------------------------------------------------------
# helpers (independent of the engine's own time handling: zoneinfo + datetime)
# ---------------------------------------------------------------------------------------------------------------------
def ep(s):
    """'YYYY-MM-DD HH:MM' New York wall clock -> epoch seconds UTC."""
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=NYZ).timestamp())


def mk(start, rows, res=5, **kw):
    """Hand-built consecutive bars of `res` minutes from `start` (New York time); rows are (o, h, l, c)."""
    t0 = ep(start)
    o, h, l, c = zip(*rows)
    return E.Bars([t0 + i * res * 60 for i in range(len(rows))], o, h, l, c, res, **kw)


def mk_at(times, rows, res=5, **kw):
    """Hand-built bars at explicit New York times."""
    o, h, l, c = zip(*rows)
    return E.Bars([ep(s) for s in times], o, h, l, c, res, **kw)


def sig(n, **at):
    """Direction array of length n; sig(5, long=[0], short=[3])."""
    d = np.zeros(n, dtype=int)
    for i in at.get("long", []):
        d[i] = 1
    for i in at.get("short", []):
        d[i] = -1
    return d


def trades(bars, direction, **kw):
    return E.run(bars, E.Signals(direction, **kw)).trades


def flat(c, n):
    """n dull bars around price c."""
    return [(c, c + 0.2, c - 0.2, c)] * n


def local(t):
    return datetime.fromtimestamp(int(t), NYZ)


def synth_1m(session_dates, seed=1, drop=None, start_price=15000.0):
    """Random-walk 1-minute bars for the given trading days: each runs 18:00 ET of the previous calendar day to
    16:15 ET.  drop(date_str, minute_of_day) -> True removes a bar.  Built with zoneinfo only."""
    rng = np.random.default_rng(seed)
    T, O, H, L, C = [], [], [], [], []
    px = start_price
    for ds in session_dates:
        d = datetime.strptime(ds, "%Y-%m-%d")
        start = (d - timedelta(days=1)).replace(hour=18, minute=0, tzinfo=NYZ)
        t0 = int(start.timestamp())
        px = round((px + rng.normal(0, 8)) * 4) / 4
        for k in range(22 * 60 + 15):
            t = t0 + 60 * k
            lt = local(t)
            mod = lt.hour * 60 + lt.minute
            o = px
            c = round((o + rng.normal(0, 2.0)) * 4) / 4
            h = max(o, c) + round(abs(rng.normal(0, 1.0)) * 4) / 4
            l = min(o, c) - round(abs(rng.normal(0, 1.0)) * 4) / 4
            px = c
            if drop is not None and drop(ds, mod):
                continue
            T.append(t); O.append(o); H.append(h); L.append(l); C.append(c)
    return (np.array(T, dtype="int64"), np.array(O), np.array(H), np.array(L), np.array(C))


def bars_from_1m(m1, res, anchor="00:00"):
    t, o, h, l, c = m1
    counts = E.rth_counts(t)
    if res == 1:
        return E.Bars(t, o, h, l, c, 1, rth_counts=counts)
    r = E.resample_1m(t, o, h, l, c, res, anchor)
    return E.Bars(r["t"], r["o"], r["h"], r["l"], r["c"], res, tmin_end=r["tmin_end"], rth_counts=counts)


def read(path):
    with open(path) as f:
        return f.read()


def one(tc, df):
    tc.assertEqual(len(df), 1, f"expected exactly one trade, got {len(df)}")
    return df.iloc[0]


D0 = "2024-01-10 10:00"       # a Wednesday, regular session


# ---------------------------------------------------------------------------------------------------------------------
# 1. fill rules
# ---------------------------------------------------------------------------------------------------------------------
class TestFillRules(unittest.TestCase):
    def test_market_entry_fills_at_next_open(self):
        b = mk(D0, [(100, 101, 99, 100), (100.5, 102, 100, 101.5), (101.5, 103, 101, 102), (102, 102.5, 101.5, 102)])
        t = one(self, trades(b, sig(4, long=[0]), max_bars=2))
        self.assertEqual((t.signal_bar, t.entry_bar, t.exit_bar), (0, 1, 2))
        self.assertEqual(t.order_type, "market")
        self.assertEqual(t.entry_price, 100.5)                 # open of the bar after the signal bar, no slippage
        self.assertEqual(t.exit_price, 102.0)                  # close of the 2nd bar held
        self.assertEqual(t.exit_reason, "bars")
        self.assertAlmostEqual(t.gross_pts, 1.5)
        self.assertAlmostEqual(t.slippage_pts, 0.0)
        self.assertAlmostEqual(t.net_pts, 0.75)
        self.assertEqual(t.bars_held, 2)
        self.assertAlmostEqual(t.minutes_held, 10.0)
        self.assertAlmostEqual(t.mae_pts, 0.5)                 # entry 100.5, lowest low 100
        self.assertAlmostEqual(t.mfe_pts, 2.5)                 # highest high 103
        self.assertEqual(str(t.entry_time), "2024-01-10 10:05:00-05:00")
        self.assertEqual(str(t.exit_time), "2024-01-10 10:15:00-05:00")

    def test_short_market_entry(self):
        b = mk(D0, [(100, 101, 99, 100), (100.5, 101, 99, 99.5), (99.5, 100, 98, 98.5), (98.5, 99, 98, 98.5)])
        t = one(self, trades(b, sig(4, short=[0]), max_bars=2))
        self.assertEqual(t.direction, -1)
        self.assertEqual(t.entry_price, 100.5)
        self.assertEqual(t.exit_price, 98.5)
        self.assertAlmostEqual(t.gross_pts, 2.0)
        self.assertAlmostEqual(t.net_pts, 1.25)
        self.assertAlmostEqual(t.mae_pts, 0.5)                 # highest high 101 vs entry 100.5
        self.assertAlmostEqual(t.mfe_pts, 2.5)                 # lowest low 98

    def test_stop_entry_fills_when_price_is_touched(self):
        b = mk(D0, [(100, 100.5, 99.5, 100), (100, 100.9, 99.8, 100.2), (100.2, 101, 100.1, 100.8),
                    (100.8, 102, 100.5, 101.5), (101.5, 101.6, 101, 101.2)])
        t = one(self, trades(b, sig(5, long=[0]), order="stop", price=101.0, max_bars=2))
        self.assertEqual(t.entry_bar, 2)                       # bar 1 high 100.9 < 101: no fill; bar 2 high == 101: fill
        self.assertEqual(t.entry_price, 101.25)                # stop price + 1 tick
        self.assertEqual(t.exit_bar, 3)
        self.assertEqual(t.exit_price, 101.5)
        self.assertAlmostEqual(t.gross_pts, 0.25)
        self.assertAlmostEqual(t.slippage_pts, 0.25)
        self.assertAlmostEqual(t.net_pts, -0.5)
        self.assertAlmostEqual(t.mae_pts, 1.15)                # 101.25 - 100.1 (entry-bar low counts as adverse)
        self.assertAlmostEqual(t.mfe_pts, 0.75)                # 102 - 101.25
        # one tick short of the stop price never fills
        b2 = mk(D0, [(100, 100.5, 99.5, 100), (100, 100.9, 99.8, 100.2), (100.2, 100.99, 100.1, 100.8)])
        self.assertEqual(len(trades(b2, sig(3, long=[0]), order="stop", price=101.0)), 0)

    def test_stop_entry_gap_fills_at_open(self):
        b = mk(D0, [(100, 100.5, 99.5, 100), (102, 103, 101.5, 102.5), (102.5, 103, 102, 102.8)])
        t = one(self, trades(b, sig(3, long=[0]), order="stop", price=101.0, max_bars=1))
        self.assertEqual(t.entry_price, 102.25)                # opens beyond the stop: open + 1 tick
        self.assertAlmostEqual(t.gross_pts, 0.25)              # exit at the close 102.5
        b = mk(D0, [(100, 100.5, 99.5, 100), (98, 98.5, 97, 97.5), (97.5, 98, 97, 97.5)])
        t = one(self, trades(b, sig(3, short=[0]), order="stop", price=99.0, max_bars=1))
        self.assertEqual(t.entry_price, 97.75)                 # sell stop: open - 1 tick
        self.assertAlmostEqual(t.gross_pts, 0.25)              # short from 97.75, close 97.5

    def test_sell_stop_entry_touch(self):
        b = mk(D0, [(100, 100.5, 99.5, 100), (100, 100.2, 99, 99.5), (99.5, 99.6, 99.2, 99.4)])
        t = one(self, trades(b, sig(3, short=[0]), order="stop", price=99.0, max_bars=1))
        self.assertEqual(t.entry_price, 98.75)
        self.assertAlmostEqual(t.gross_pts, 98.75 - 99.5)

    def test_limit_touched_but_not_traded_through_does_not_fill(self):
        b = mk(D0, [(100, 100.5, 99.5, 100), (100, 100.5, 99.0, 99.5), (99.5, 99.8, 98.9, 99.2),
                    (99.2, 99.6, 99.0, 99.4)])
        t = one(self, trades(b, sig(4, long=[0]), order="limit", price=99.0, max_bars=1))
        self.assertEqual(t.entry_bar, 2)                       # bar 1 only touches 99.0; bar 2 trades through it
        self.assertEqual(t.entry_price, 99.0)                  # at the limit, no slippage
        self.assertAlmostEqual(t.slippage_pts, 0.0)
        self.assertAlmostEqual(t.gross_pts, 0.2)               # exit at the close 99.2
        self.assertAlmostEqual(t.net_pts, -0.55)
        # touched on every bar, never through: no trade at all
        b2 = mk(D0, [(100, 100.5, 99.5, 100), (100, 100.5, 99.0, 99.5), (99.5, 99.8, 99.0, 99.2)])
        self.assertEqual(len(trades(b2, sig(3, long=[0]), order="limit", price=99.0)), 0)
        # sell limit
        b3 = mk(D0, [(100, 100.5, 99.5, 100), (100, 101, 99.5, 100.5), (100.5, 101.2, 100.2, 100.9),
                     (100.9, 101, 100.5, 100.6)])
        t = one(self, trades(b3, sig(4, short=[0]), order="limit", price=101.0, max_bars=1))
        self.assertEqual((t.entry_bar, t.entry_price), (2, 101.0))
        self.assertAlmostEqual(t.gross_pts, 101.0 - 100.9)

    def test_limit_fills_at_open_when_bar_opens_beyond_in_favour(self):
        b = mk(D0, [(100, 100.5, 99.5, 100), (98.5, 99.2, 98.2, 98.8), (98.8, 99, 98.5, 98.9)])
        t = one(self, trades(b, sig(3, long=[0]), order="limit", price=99.0, max_bars=1))
        self.assertEqual(t.entry_price, 98.5)                  # better than the limit: the open
        self.assertAlmostEqual(t.gross_pts, 0.3)
        b = mk(D0, [(100, 100.5, 99.5, 100), (101.5, 101.8, 101.2, 101.4), (101.4, 101.5, 101, 101.2)])
        t = one(self, trades(b, sig(3, short=[0]), order="limit", price=101.0, max_bars=1))
        self.assertEqual(t.entry_price, 101.5)
        self.assertAlmostEqual(t.gross_pts, 0.1)

    def test_protective_stop_exits_at_stop_price(self):
        b = mk(D0, [(100, 100.5, 99.5, 100), (100, 100.5, 99.5, 100.2), (100.2, 100.5, 98, 99), (99, 99.5, 98.5, 99)])
        t = one(self, trades(b, sig(4, long=[0]), stop=98.0))
        self.assertEqual((t.entry_bar, t.exit_bar, t.exit_reason), (1, 2, "stop"))
        self.assertEqual(t.exit_price, 97.75)                  # low == stop counts; stop price - 1 tick
        self.assertAlmostEqual(t.gross_pts, -2.25)
        self.assertAlmostEqual(t.slippage_pts, 0.25)
        self.assertAlmostEqual(t.net_pts, -3.0)
        self.assertAlmostEqual(t.risk_pts, 2.0)
        self.assertAlmostEqual(t.r_multiple, -1.5)
        self.assertAlmostEqual(t.mae_pts, 2.0)                 # capped at the stop price
        self.assertAlmostEqual(t.mfe_pts, 0.5)
        self.assertEqual(t.stop_price, 98.0)
        # one tick above the stop: not stopped
        b2 = mk(D0, [(100, 100.5, 99.5, 100), (100, 100.5, 99.5, 100.2), (100.2, 100.5, 98.01, 99)])
        self.assertEqual(trades(b2, sig(3, long=[0]), stop=98.0, allow_multi_day=True).iloc[0].exit_reason, "end_of_data")
        # short
        b3 = mk(D0, [(100, 100.5, 99.5, 100), (100, 100.5, 99.5, 100.2), (100.2, 102, 99.9, 101.5)])
        t = one(self, trades(b3, sig(3, short=[0]), stop=102.0))
        self.assertEqual((t.exit_reason, t.exit_price), ("stop", 102.25))
        self.assertAlmostEqual(t.gross_pts, -2.25)

    def test_gap_through_stop_exits_at_open(self):
        b = mk(D0, [(100, 100.5, 99.5, 100), (100, 100.5, 99.5, 100.2), (97, 97.5, 96, 96.5)])
        t = one(self, trades(b, sig(3, long=[0]), stop=98.0))
        self.assertEqual((t.exit_reason, t.exit_price), ("stop", 96.75))     # open 97 - 1 tick, not the stop price
        self.assertAlmostEqual(t.gross_pts, -3.25)
        self.assertAlmostEqual(t.net_pts, -4.0)
        self.assertAlmostEqual(t.mae_pts, 3.0)
        b = mk(D0, [(100, 100.5, 99.5, 100), (100, 100.5, 99.5, 100.2), (103, 103.5, 102.5, 103.2)])
        t = one(self, trades(b, sig(3, short=[0]), stop=102.0))
        self.assertEqual((t.exit_reason, t.exit_price), ("stop", 103.25))
        self.assertAlmostEqual(t.gross_pts, -3.25)

    def test_target_needs_trade_through(self):
        b = mk(D0, [(100, 100.5, 99.5, 100), (100, 100.5, 99.8, 100.2), (100.2, 102, 99.5, 101),
                    (101, 102.25, 100.5, 102), (102, 102.5, 101.5, 102)])
        t = one(self, trades(b, sig(5, long=[0]), target=102.0))
        self.assertEqual((t.exit_bar, t.exit_reason), (3, "target"))        # bar 2 only touches 102
        self.assertEqual(t.exit_price, 102.0)                               # at the target, no slippage
        self.assertAlmostEqual(t.gross_pts, 2.0)
        self.assertAlmostEqual(t.slippage_pts, 0.0)
        self.assertAlmostEqual(t.net_pts, 1.25)
        self.assertAlmostEqual(t.mae_pts, 0.5)
        self.assertAlmostEqual(t.mfe_pts, 2.0)
        self.assertEqual(t.target_price, 102.0)
        b = mk(D0, [(100, 100.5, 99.5, 100), (100, 100.5, 99.8, 100.2), (100.2, 100.4, 98, 99),
                    (99, 99.5, 97.9, 98.2)])
        t = one(self, trades(b, sig(4, short=[0]), target=98.0))
        self.assertEqual((t.exit_bar, t.exit_reason, t.exit_price), (3, "target", 98.0))
        self.assertAlmostEqual(t.gross_pts, 2.0)

    def test_target_gap_fills_at_target_not_better(self):
        b = mk(D0, [(100, 100.5, 99.5, 100), (100, 100.5, 99.8, 100.2), (103, 103.5, 102.5, 103.2)])
        t = one(self, trades(b, sig(3, long=[0]), target=102.0))
        self.assertEqual((t.exit_reason, t.exit_price), ("target", 102.0))

    def test_stop_and_target_in_one_bar_takes_the_stop(self):
        b = mk(D0, [(100, 100.5, 99.5, 100), (100, 100.5, 99.8, 100.2), (100.2, 103, 97.5, 101)])
        t = one(self, trades(b, sig(3, long=[0]), stop=98.0, target=102.0))
        self.assertEqual((t.exit_reason, t.exit_price), ("stop", 97.75))
        t = one(self, trades(b, sig(3, short=[0]), stop=102.0, target=98.0))
        self.assertEqual((t.exit_reason, t.exit_price), ("stop", 102.25))

    def test_entry_bar_of_stop_entry_stop_counts_target_does_not(self):
        # buy stop 101, protective stop 99.5, target 102.  The entry bar spans both: only the stop counts.
        b = mk(D0, [(100, 100.5, 99.5, 100), (100, 103, 99, 102.5), (102.5, 103, 102, 102.8)])
        t = one(self, trades(b, sig(3, long=[0]), order="stop", price=101.0, stop=99.5, target=102.0))
        self.assertEqual((t.entry_bar, t.exit_bar, t.exit_reason), (1, 1, "stop"))
        self.assertEqual(t.entry_price, 101.25)
        self.assertEqual(t.exit_price, 99.25)                  # the stop price (not the bar's open) - 1 tick
        self.assertAlmostEqual(t.gross_pts, -2.0)
        self.assertAlmostEqual(t.slippage_pts, 0.5)            # one tick in, one tick out
        self.assertAlmostEqual(t.net_pts, -2.75)
        self.assertEqual(t.bars_held, 1)
        self.assertAlmostEqual(t.mae_pts, 1.75)
        self.assertAlmostEqual(t.mfe_pts, 0.0)
        # the same without the adverse move: the target is NOT taken on the entry bar (high 103 > 102),
        # it is taken on the next bar, at the target
        b = mk(D0, [(100, 100.5, 99.5, 100), (100, 103, 99.8, 102.5), (102.5, 102.6, 101.9, 102.2),
                    (102.2, 102.3, 102, 102.1)])
        t = one(self, trades(b, sig(4, long=[0]), order="stop", price=101.0, stop=99.5, target=102.0))
        self.assertEqual((t.entry_bar, t.exit_bar, t.exit_reason, t.exit_price), (1, 2, "target", 102.0))
        self.assertAlmostEqual(t.gross_pts, 0.75)
        self.assertAlmostEqual(t.net_pts, 0.0)

    def test_entry_bar_of_limit_entry_stop_counts_target_does_not(self):
        b = mk(D0, [(100, 100.5, 99.5, 100), (99.5, 100.5, 97.9, 99.8), (99.8, 100, 99.5, 99.9)])
        t = one(self, trades(b, sig(3, long=[0]), order="limit", price=99.0, stop=98.0, target=100.0))
        self.assertEqual((t.entry_bar, t.exit_bar, t.exit_reason), (1, 1, "stop"))
        self.assertEqual((t.entry_price, t.exit_price), (99.0, 97.75))
        self.assertAlmostEqual(t.gross_pts, -1.25)
        self.assertAlmostEqual(t.slippage_pts, 0.25)           # limit entry: no slippage; stop exit: one tick
        self.assertAlmostEqual(t.net_pts, -2.0)
        # stop not reached: the target (high 100.5 > 100) still does not count on the entry bar
        b = mk(D0, [(100, 100.5, 99.5, 100), (99.5, 100.5, 98.5, 99.8), (99.8, 100.2, 99.5, 100.1)])
        t = one(self, trades(b, sig(3, long=[0]), order="limit", price=99.0, stop=98.0, target=100.0))
        self.assertEqual((t.exit_bar, t.exit_reason, t.exit_price), (2, "target", 100.0))
        # short limit entry bar
        b = mk(D0, [(100, 100.5, 99.5, 100), (100.5, 102.1, 99, 100.2), (100.2, 100.4, 100, 100.1)])
        t = one(self, trades(b, sig(3, short=[0]), order="limit", price=101.0, stop=102.0, target=100.0))
        self.assertEqual((t.entry_price, t.exit_bar, t.exit_reason, t.exit_price), (101.0, 1, "stop", 102.25))

    def test_entry_bar_of_market_entry_is_a_full_bar(self):
        # a market order is filled at the open, so the whole bar follows the fill: stop and target both count
        b = mk(D0, [(100, 100.5, 99.5, 100), (100, 101.5, 99.9, 101.2), (101.2, 101.5, 101, 101.3)])
        t = one(self, trades(b, sig(3, long=[0]), target=101.0))
        self.assertEqual((t.exit_bar, t.exit_reason, t.exit_price, t.bars_held), (1, "target", 101.0, 1))
        t = one(self, trades(b, sig(3, long=[0]), stop=99.9))
        self.assertEqual((t.exit_bar, t.exit_reason, t.exit_price), (1, "stop", 99.65))
        t = one(self, trades(b, sig(3, long=[0]), stop=99.9, target=101.0))
        self.assertEqual(t.exit_reason, "stop")
        # a stop that is already beyond the open when the order fills is hit at once, at the open
        t = one(self, trades(b, sig(3, long=[0]), stop=100.5))
        self.assertEqual((t.exit_bar, t.exit_reason, t.exit_price), (1, "stop", 99.75))
        self.assertAlmostEqual(t.net_pts, -1.0)
        self.assertTrue(math.isnan(t.risk_pts))

    def test_stop_entry_gap_keeps_protective_stop_price(self):
        # buy stop 101 gaps to 102; the protective stop 100 is below the bar's low 101.5 -> survives the entry bar
        b = mk(D0, [(100, 100.5, 99.5, 100), (102, 103, 101.5, 102.5), (102.5, 102.6, 99.8, 100)])
        t = one(self, trades(b, sig(3, long=[0]), order="stop", price=101.0, stop=100.0))
        self.assertEqual((t.entry_price, t.exit_bar, t.exit_price), (102.25, 2, 99.75))
        self.assertAlmostEqual(t.risk_pts, 2.25)

    def test_two_sided_orders_first_fill_cancels_the_other(self):
        rows = [(100, 100.5, 99.5, 100), (100, 101.5, 99.6, 101.2), (101.2, 101.4, 98, 98.5), (98.5, 99, 98, 98.5)]
        b = mk(D0, rows)
        m = np.array([True, False, False, False])
        s = E.Signals(long=dict(entry=m, order="stop", price=np.full(4, 101.0)),
                      short=dict(entry=m, order="stop", price=np.full(4, 99.0)), max_bars=5, allow_multi_day=True)
        r = E.run(b, s)
        t = one(self, r.trades)
        self.assertEqual((t.direction, t.entry_bar, t.entry_price), (1, 1, 101.25))   # short at 99 never opens
        self.assertEqual(t.exit_reason, "end_of_data")
        self.assertEqual(r.diag["orders"], 2)
        self.assertEqual(r.diag["fills"], 1)

    def test_two_sided_orders_both_reached_in_one_bar(self):
        # open 100.2 is nearer to the buy stop (101) than to the sell stop (99): the long is taken first, and its
        # protective stop (99, the other side) is then hit on the entry bar
        b = mk(D0, [(100, 100.5, 99.5, 100), (100.2, 101.5, 98.5, 99), (99, 99.5, 98.5, 99)])
        m = np.array([True, False, False])
        s = E.Signals(long=dict(entry=m, order="stop", price=np.full(3, 101.0), stop=np.full(3, 99.0)),
                      short=dict(entry=m, order="stop", price=np.full(3, 99.0), stop=np.full(3, 101.0)))
        t = one(self, E.run(b, s).trades)
        self.assertEqual((t.direction, t.entry_price, t.exit_reason, t.exit_price), (1, 101.25, "stop", 98.75))
        self.assertAlmostEqual(t.net_pts, -3.25)
        # open nearer to the sell stop: the short is taken first
        b = mk(D0, [(100, 100.5, 99.5, 100), (99.7, 101.5, 98.5, 99), (99, 99.5, 98.5, 99)])
        t = one(self, E.run(b, s).trades)
        self.assertEqual((t.direction, t.entry_price, t.exit_reason, t.exit_price), (-1, 98.75, "stop", 101.25))
        # contradictory market orders on the same bar: no trade
        s2 = E.Signals(long=dict(entry=m), short=dict(entry=m))
        r = E.run(b, s2)
        self.assertEqual((len(r.trades), r.diag["conflicts"]), (0, 1))


# ---------------------------------------------------------------------------------------------------------------------
# 2. slippage and cost arithmetic
# ---------------------------------------------------------------------------------------------------------------------
class TestCosts(unittest.TestCase):
    def test_constants(self):
        self.assertEqual((E.TICK, E.SLIPPAGE, E.COST_RT), (0.25, 0.25, 0.75))

    def test_stop_in_stop_out(self):
        b = mk(D0, [(100, 100.5, 99.5, 100), (100, 101.2, 99.9, 101), (101, 101.1, 99.8, 100)])
        t = one(self, trades(b, sig(3, long=[0]), order="stop", price=101.0, stop=100.0))
        self.assertEqual((t.entry_price, t.exit_price), (101.25, 99.75))
        self.assertAlmostEqual(t.gross_pts, -1.5)              # 1.0 between the two stop prices + 2 ticks
        self.assertAlmostEqual(t.slippage_pts, 0.5)
        self.assertAlmostEqual(t.cost_pts, 0.75)
        self.assertAlmostEqual(t.net_pts, -2.25)
        self.assertAlmostEqual(t.risk_pts, 1.25)               # entry fill to stop price
        self.assertAlmostEqual(t.r_multiple, -2.25 / 1.25)

    def test_short_stop_in_stop_out(self):
        b = mk(D0, [(100, 100.5, 99.5, 100), (100, 100.1, 98.8, 99), (99, 100.2, 98.9, 100)])
        t = one(self, trades(b, sig(3, short=[0]), order="stop", price=99.0, stop=100.0))
        self.assertEqual((t.entry_price, t.exit_price), (98.75, 100.25))
        self.assertAlmostEqual(t.gross_pts, -1.5)
        self.assertAlmostEqual(t.net_pts, -2.25)

    def test_market_in_target_out_pays_only_round_trip(self):
        b = mk(D0, [(100, 100.5, 99.5, 100), (100, 100.5, 99.8, 100.2), (100.2, 103.1, 100, 103)])
        t = one(self, trades(b, sig(3, long=[0]), target_pts=3.0))
        self.assertAlmostEqual(t.gross_pts, 3.0)
        self.assertAlmostEqual(t.slippage_pts, 0.0)
        self.assertAlmostEqual(t.net_pts, 2.25)

    def test_stop_pts_and_target_r_are_measured_from_the_fill(self):
        b = mk(D0, [(100, 100.5, 99.5, 100), (100, 101.2, 99.9, 101), (101, 105.3, 100.9, 105.2),
                    (105.2, 105.3, 105, 105.1)])
        t = one(self, trades(b, sig(4, long=[0]), order="stop", price=101.0, stop_pts=2.0, target_r=2.0))
        self.assertEqual(t.entry_price, 101.25)
        self.assertEqual(t.stop_price, 99.25)                  # fill - 2
        self.assertEqual(t.target_price, 105.25)               # fill + 2R
        self.assertAlmostEqual(t.risk_pts, 2.0)
        self.assertEqual((t.exit_reason, t.exit_price), ("target", 105.25))   # bar 2 high 105.3 > 105.25
        self.assertAlmostEqual(t.net_pts, 4.0 - 0.75)
        self.assertAlmostEqual(t.r_multiple, 3.25 / 2.0)

    def test_time_exit_and_eod_exit_pay_no_slippage(self):
        b = mk(D0, [(100, 100.5, 99.5, 100)] + flat(100, 4))
        t = one(self, trades(b, sig(5, long=[0]), exit_time="10:20"))
        self.assertEqual((t.exit_reason, t.exit_bar), ("time", 3))          # the bar 10:15-10:20
        self.assertAlmostEqual(t.gross_pts, 0.0)
        self.assertAlmostEqual(t.net_pts, -0.75)


# ---------------------------------------------------------------------------------------------------------------------
# 3. session rules: last entry, flat by 16:10, cancelled orders, multi-day switch
# ---------------------------------------------------------------------------------------------------------------------
LATE = ["2024-01-10 15:40", "2024-01-10 15:45", "2024-01-10 15:50", "2024-01-10 15:55", "2024-01-10 16:00",
        "2024-01-10 16:05", "2024-01-10 16:10", "2024-01-10 18:00", "2024-01-10 18:05", "2024-01-10 18:10"]


class TestSessionRules(unittest.TestCase):
    def late(self, rows=None):
        return mk_at(LATE, rows or flat(100, 10))

    def test_market_entry_needs_a_bar_that_opens_by_last_entry(self):
        b = self.late()
        t = one(self, trades(b, sig(10, long=[2])))             # signal at the 15:55 close -> fill at the 15:55 open
        self.assertEqual(str(t.entry_time), "2024-01-10 15:55:00-05:00")
        self.assertEqual(len(trades(b, sig(10, long=[3]))), 0)   # next bar opens 16:00 > 15:55: no entry
        self.assertEqual(len(trades(b, sig(10, long=[4, 5]))), 0)
        # a configurable last-entry time
        t = one(self, trades(b, sig(10, long=[0, 1, 2]), last_entry="15:45", max_bars=1))
        self.assertEqual(str(t.entry_time), "2024-01-10 15:45:00-05:00")

    def test_stop_and_limit_entries_need_a_bar_that_ends_by_last_entry(self):
        rows = flat(100, 10)
        rows[3] = (100, 101.5, 99.8, 101)                       # 15:55-16:00 bar trades through 101
        b = self.late(rows)
        self.assertEqual(len(trades(b, sig(10, long=[1]), order="stop", price=101.0)), 0)   # would fill after 15:55
        rows = flat(100, 10)
        rows[2] = (100, 101.5, 99.8, 101)                       # 15:50-15:55 bar: ends at 15:55 -> allowed
        b = self.late(rows)
        t = one(self, trades(b, sig(10, long=[1]), order="stop", price=101.0))
        self.assertEqual(str(t.entry_time), "2024-01-10 15:50:00-05:00")
        rows = flat(100, 10)
        rows[3] = (100, 100.2, 98.5, 99)
        self.assertEqual(len(trades(self.late(rows), sig(10, long=[1]), order="limit", price=99.0)), 0)

    def test_first_entry(self):
        b = self.late()
        t = one(self, trades(b, sig(10, long=[0, 1]), first_entry="15:50", max_bars=1))
        self.assertEqual(str(t.entry_time), "2024-01-10 15:50:00-05:00")

    def test_position_is_closed_at_the_close_of_the_last_bar_ending_by_1610(self):
        rows = flat(100, 10)
        rows[5] = (100, 100.6, 99.9, 100.5)                     # the 16:05-16:10 bar
        rows[6] = (100.5, 105, 100.5, 105)                      # 16:10-16:15: must not be used
        b = self.late(rows)
        t = one(self, trades(b, sig(10, long=[2])))
        self.assertEqual(t.exit_reason, "eod")
        self.assertEqual(str(t.exit_time), "2024-01-10 16:10:00-05:00")
        self.assertEqual(t.exit_bar, 5)
        self.assertEqual(t.exit_price, 100.5)
        self.assertEqual(t.bars_held, 3)
        self.assertAlmostEqual(t.net_pts, 0.5 - 0.75)

    def test_flat_bar_for_other_resolutions(self):
        # 15-minute bars: the 16:00-16:15 bar ends after 16:10, so the position is closed at 16:00
        b15 = mk_at(["2024-01-10 15:30", "2024-01-10 15:45", "2024-01-10 16:00", "2024-01-10 18:00"], flat(100, 4), res=15)
        t = one(self, trades(b15, sig(4, long=[0])))
        self.assertEqual((str(t.entry_time), str(t.exit_time)), ("2024-01-10 15:45:00-05:00", "2024-01-10 16:00:00-05:00"))
        self.assertEqual(t.exit_reason, "eod")
        # 1-minute bars: closed at the close of the 16:09 bar
        b1 = mk("2024-01-10 15:50", flat(100, 25), res=1)
        t = one(self, trades(b1, sig(25, long=[4])))
        self.assertEqual((str(t.entry_time), str(t.exit_time)), ("2024-01-10 15:55:00-05:00", "2024-01-10 16:10:00-05:00"))
        self.assertEqual(t.bars_held, 15)
        # 30-minute bars: 16:00-16:30 is cut at 16:15 and ends after 16:10 -> flat at 16:00
        b30 = mk_at(["2024-01-10 15:00", "2024-01-10 15:30", "2024-01-10 16:00"], flat(100, 3), res=30)
        t = one(self, trades(b30, sig(3, long=[0])))
        self.assertEqual((str(t.entry_time), str(t.exit_time)), ("2024-01-10 15:30:00-05:00", "2024-01-10 16:00:00-05:00"))

    def test_pending_orders_are_cancelled_at_the_end_of_day(self):
        rows = flat(100, 10)
        rows[7] = (100, 103, 99.9, 102)                         # 18:00 bar of the NEXT trading day trades through 101
        b = self.late(rows)
        self.assertEqual(len(trades(b, sig(10, long=[0]), order="stop", price=101.0)), 0)
        self.assertEqual(len(trades(b, sig(10, long=[0]), order="stop", price=101.0, expiry_bars=50)), 0)
        # swing mode with expiry_bars: the order survives the end of day and fills in the evening
        t = one(self, trades(b, sig(10, long=[0]), order="stop", price=101.0, expiry_bars=50, allow_multi_day=True))
        self.assertEqual(str(t.entry_time), "2024-01-10 18:00:00-05:00")
        self.assertEqual(str(t.entry_day.date()), "2024-01-11")
        # swing mode without expiry_bars: still bound to its own trading day
        self.assertEqual(len(trades(b, sig(10, long=[0]), order="stop", price=101.0, allow_multi_day=True)), 0)

    def test_market_signal_on_the_last_bar_of_a_day_enters_at_the_evening_open(self):
        b = self.late()
        t = one(self, trades(b, sig(10, long=[6]), max_bars=2))          # signal at the 16:15 close
        self.assertEqual(str(t.entry_time), "2024-01-10 18:00:00-05:00")
        self.assertEqual(str(t.entry_day.date()), "2024-01-11")
        self.assertEqual(t.exit_reason, "bars")

    def test_orders_are_not_carried_out_of_a_day_that_ends_early(self):
        # a half day: the data stops at 13:10; the next bar is the 18:00 open of the next trading day
        times = ["2024-11-29 13:00", "2024-11-29 13:05", "2024-11-29 13:10", "2024-12-01 18:00", "2024-12-01 18:05",
                 "2024-12-01 18:10", "2024-12-01 18:15"]
        rows = flat(100, 7)
        rows[3] = (100, 102, 99.9, 101.5)
        b = mk_at(times, rows)
        self.assertEqual([str(x) for x in b.tday[[2, 3]]], ["2024-11-29", "2024-12-02"])
        r = E.run(b, E.Signals(sig(7, long=[2]), max_bars=1))
        self.assertEqual((len(r.trades), r.diag["dropped"], r.diag["void"], r.diag["orders"]), (0, 1, 0, 0))
        r = E.run(b, E.Signals(sig(7, long=[2]), order="stop", price=101.0, expiry_bars=3))
        self.assertEqual((len(r.trades), r.diag["dropped"]), (0, 1))
        # an earlier bar of the short day still works inside that day
        self.assertEqual(len(trades(b, sig(7, long=[0]), max_bars=1)), 1)
        # swing mode may carry the order
        t = one(self, trades(b, sig(7, long=[2]), max_bars=1, allow_multi_day=True))
        self.assertEqual(str(t.entry_time), "2024-12-01 18:00:00-05:00")
        t = one(self, trades(b, sig(7, long=[2]), order="stop", price=101.0, expiry_bars=3, allow_multi_day=True))
        self.assertEqual((str(t.entry_time), t.entry_price), ("2024-12-01 18:00:00-05:00", 101.25))
        # the callback path follows the same rule
        got = []

        def on_bar(ctx):
            if ctx.i == 2:
                got.append(ctx.buy_market(max_bars=1))
        r = E.run(b, E.Callback(on_bar))
        self.assertEqual((got, len(r.trades), r.diag["dropped"]), ([False], 0, 1))

    def test_positions_never_cross_the_end_of_day_by_default(self):
        b = self.late()
        r = E.run(b, E.Signals(sig(10, long=[2])))
        self.assertTrue(r.tradeify_usable)
        t = one(self, r.trades)
        self.assertEqual(t.exit_reason, "eod")
        self.assertLess(t.exit_bar, 6)

    def test_multi_day_switch_holds_across_the_break_and_checks_the_stop_at_the_next_open(self):
        rows = flat(100, 10)
        rows[7] = (96, 96.5, 95.5, 96.2)                        # the evening session opens through the stop
        b = self.late(rows)
        r = E.run(b, E.Signals(sig(10, long=[2]), stop=98.0, allow_multi_day=True))
        self.assertFalse(r.tradeify_usable)
        t = one(self, r.trades)
        self.assertEqual((t.exit_reason, t.exit_bar), ("stop", 7))
        self.assertEqual(t.exit_price, 95.75)                   # the next bar's open - 1 tick
        self.assertAlmostEqual(t.net_pts, -4.25 - 0.75)
        self.assertEqual(str(t.exit_time), "2024-01-10 18:05:00-05:00")
        # the same signal intraday is flat at 16:10 with no loss
        t = one(self, trades(b, sig(10, long=[2]), stop=98.0))
        self.assertEqual((t.exit_reason, t.exit_price), ("eod", 100.0))

    def test_multi_day_position_open_at_the_end_of_the_data(self):
        b = self.late()
        t = one(self, trades(b, sig(10, long=[2]), allow_multi_day=True))
        self.assertEqual((t.exit_reason, t.exit_bar), ("end_of_data", 9))

    def test_overnight_position_is_held_through_one_trading_day(self):
        times = ["2024-01-09 18:00", "2024-01-09 18:05", "2024-01-09 23:55", "2024-01-10 00:00", "2024-01-10 09:30",
                 "2024-01-10 16:00", "2024-01-10 16:05", "2024-01-10 16:10", "2024-01-10 18:00"]
        b = mk_at(times, flat(100, 9))
        t = one(self, trades(b, sig(9, long=[0])))
        self.assertEqual((str(t.entry_time), str(t.exit_time)), ("2024-01-09 18:05:00-05:00", "2024-01-10 16:10:00-05:00"))
        self.assertEqual(t.exit_reason, "eod")
        self.assertEqual(str(t.entry_day.date()), "2024-01-10")

    def test_max_trades_per_day(self):
        b = mk(D0, flat(100, 10))
        self.assertEqual(len(trades(b, sig(10, long=[0, 3, 6]), max_bars=1)), 3)
        self.assertEqual(len(trades(b, sig(10, long=[0, 3, 6]), max_bars=1, max_trades_per_day=1)), 1)
        self.assertEqual(len(trades(b, sig(10, long=[0, 3, 6]), max_bars=1, max_trades_per_day=2)), 2)
        # the count restarts with the next trading day (18:00)
        b2 = mk_at(["2024-01-10 15:00", "2024-01-10 15:05", "2024-01-10 15:10", "2024-01-10 15:15",
                    "2024-01-10 18:00", "2024-01-10 18:05", "2024-01-10 18:10"], flat(100, 7))
        tr = trades(b2, sig(7, long=[0, 2, 4]), max_bars=1, max_trades_per_day=1)
        self.assertEqual(list(tr.entry_bar), [1, 5])

    def test_one_position_at_a_time(self):
        b = mk(D0, flat(100, 10))
        tr = trades(b, sig(10, long=[0, 1, 2, 3]), max_bars=3)
        self.assertEqual(list(tr.entry_bar), [1, 4])            # signals at bars 1, 2 arrive while the first is open
        self.assertEqual(list(tr.exit_bar), [3, 6])


# ---------------------------------------------------------------------------------------------------------------------
# 4. exits, order life and trade management
# ---------------------------------------------------------------------------------------------------------------------
class TestExitsAndManagement(unittest.TestCase):
    def test_exit_after_n_bars(self):
        b = mk(D0, flat(100, 8))
        for nb in (1, 2, 4):
            t = one(self, trades(b, sig(8, long=[0]), max_bars=nb))
            self.assertEqual((t.entry_bar, t.exit_bar, t.bars_held, t.exit_reason), (1, nb, nb, "bars"))
        # a per-signal array of max_bars
        mb = np.array([3.0] * 8)
        t = one(self, trades(b, sig(8, long=[0]), max_bars=mb))
        self.assertEqual(t.exit_bar, 3)

    def test_exit_at_time_of_day(self):
        b = mk(D0, flat(100, 12))
        t = one(self, trades(b, sig(12, long=[0]), exit_time="10:30"))
        self.assertEqual((t.exit_reason, str(t.exit_time)), ("time", "2024-01-10 10:30:00-05:00"))
        self.assertEqual(t.exit_bar, 5)                         # the bar 10:25-10:30
        t = one(self, trades(b, sig(12, long=[0]), exit_time="10:32"))
        self.assertEqual(t.exit_bar, 5)                         # the last bar that ENDS by 10:32

    def test_exit_on_signal_at_next_open(self):
        rows = flat(100, 6)
        rows[4] = (101, 101.5, 100.8, 101.2)
        b = mk(D0, rows)
        x = np.zeros(6, dtype=bool)
        x[3] = True
        t = one(self, trades(b, sig(6, long=[0]), exit_long=x))
        self.assertEqual((t.exit_reason, t.exit_bar, t.exit_price), ("signal", 4, 101.0))
        self.assertEqual(t.bars_held, 3)                        # bars 1, 2, 3
        self.assertEqual(str(t.exit_time), "2024-01-10 10:20:00-05:00")
        self.assertAlmostEqual(t.net_pts, 1.0 - 0.75)
        # exit_short does nothing to a long
        t = one(self, trades(b, sig(6, long=[0]), exit_short=x, allow_multi_day=True))
        self.assertEqual(t.exit_reason, "end_of_data")

    def test_reverse_at_the_same_open(self):
        rows = flat(100, 8)
        rows[4] = (101, 101.5, 100.8, 101.2)
        b = mk(D0, rows)
        x = np.zeros(8, dtype=bool)
        x[3] = True
        tr = trades(b, sig(8, long=[0], short=[3]), exit_long=x, max_bars=6)
        self.assertEqual(len(tr), 2)
        self.assertEqual((tr.iloc[0].exit_bar, tr.iloc[0].exit_price, tr.iloc[0].exit_reason), (4, 101.0, "signal"))
        self.assertEqual((tr.iloc[1].direction, tr.iloc[1].entry_bar, tr.iloc[1].entry_price), (-1, 4, 101.0))

    def test_expiry_in_bars(self):
        rows = flat(100, 6)
        rows[3] = (100, 101.5, 99.9, 101)
        b = mk(D0, rows)
        self.assertEqual(len(trades(b, sig(6, long=[0]), order="stop", price=101.0, expiry_bars=2)), 0)
        t = one(self, trades(b, sig(6, long=[0]), order="stop", price=101.0, expiry_bars=3))
        self.assertEqual(t.entry_bar, 3)
        eb = np.array([2.0, 3, 3, 3, 3, 3])
        self.assertEqual(len(trades(b, sig(6, long=[0]), order="stop", price=101.0, expiry_bars=eb)), 0)

    def test_expiry_at_time_of_day(self):
        rows = flat(100, 6)
        rows[3] = (100, 101.5, 99.9, 101)                       # the bar 10:15-10:20
        b = mk(D0, rows)
        self.assertEqual(len(trades(b, sig(6, long=[0]), order="stop", price=101.0, expiry_time="10:15")), 0)
        t = one(self, trades(b, sig(6, long=[0]), order="stop", price=101.0, expiry_time="10:20"))
        self.assertEqual(t.entry_bar, 3)

    def test_market_order_is_for_the_next_bar_only(self):
        # the next bar is not eligible (opens after last_entry): the order is dropped, not carried forward
        b = mk_at(LATE, flat(100, 10))
        self.assertEqual(len(trades(b, sig(10, long=[4]), allow_multi_day=True)), 0)

    def test_new_signal_replaces_a_waiting_order_of_the_same_side(self):
        rows = flat(100, 6)
        rows[2] = (100, 102, 99.9, 101.5)
        b = mk(D0, rows)
        price = np.array([105.0, 101.0, 0, 0, 0, 0])
        t = one(self, trades(b, sig(6, long=[0, 1]), order="stop", price=price, max_bars=1))
        self.assertEqual((t.signal_bar, t.entry_bar, t.entry_price), (1, 2, 101.25))

    def test_nan_voids_a_signal(self):
        b = mk(D0, flat(100, 6))
        st = np.array([NAN, 99.0, 99, 99, 99, 99])
        r = E.run(b, E.Signals(sig(6, long=[0, 3]), stop=st, max_bars=1))
        self.assertEqual(list(r.trades.signal_bar), [3])
        self.assertEqual(r.diag["void"], 1)
        r = E.run(b, E.Signals(sig(6, long=[0]), order="stop", price=np.full(6, NAN)))
        self.assertEqual((len(r.trades), r.diag["void"]), (0, 1))
        # a non-positive distance voids the signal too
        r = E.run(b, E.Signals(sig(6, long=[0, 3]), stop_pts=np.array([0.0, 1, 1, 2.0, 1, 1]), max_bars=1))
        self.assertEqual((list(r.trades.signal_bar), r.diag["void"]), ([3], 1))

    def test_order_type_per_bar_and_price_ignored_for_market_orders(self):
        rows = flat(100, 8)
        rows[5] = (100, 101.5, 99.9, 101)
        b = mk(D0, rows)
        typ = np.array([E.MARKET, 0, 0, E.STOP, 0, 0, 0, 0])
        price = np.array([NAN, NAN, NAN, 101.0, NAN, NAN, NAN, NAN])
        tr = trades(b, sig(8, long=[0, 3]), order=typ, price=price, max_bars=1, expiry_bars=3)
        self.assertEqual(list(tr.order_type), ["market", "stop"])
        self.assertEqual(list(tr.entry_bar), [1, 5])
        self.assertEqual(list(tr.entry_price), [100.0, 101.25])

        def on_bar(ctx):
            if ctx.i == 0:
                self.assertTrue(ctx.order(1, "market", NAN, max_bars=1))
        self.assertEqual(len(E.run(b, E.Callback(on_bar)).trades), 1)

    def test_breakeven(self):
        rows = [(100, 100.5, 99.5, 100), (100, 100.4, 99.8, 100.2), (100.2, 102.5, 99.0, 102.2),
                (102.2, 102.4, 99.9, 100.1), (100.1, 100.3, 99.9, 100)]
        b = mk(D0, rows)
        t = one(self, trades(b, sig(5, long=[0]), stop=98.0, be_trigger_pts=2.0))
        # bar 2 reaches +2.5 (its low 99.0 is above the stop 98, still in force during that bar); the stop moves to
        # the entry price 100 at its close; bar 3 trades down to 99.9 -> out at 100 - 1 tick
        self.assertEqual((t.exit_bar, t.exit_reason, t.exit_price), (3, "stop", 99.75))
        self.assertAlmostEqual(t.net_pts, -1.0)
        self.assertEqual(t.stop_price, 98.0)                    # the table keeps the INITIAL stop
        self.assertAlmostEqual(t.risk_pts, 2.0)
        t = one(self, trades(b, sig(5, long=[0]), stop=98.0, be_trigger_r=1.0, be_offset_pts=0.5))
        self.assertEqual((t.exit_bar, t.exit_price), (3, 100.25))            # stop at entry + 0.5
        t = one(self, trades(b, sig(5, long=[0]), stop=98.0, be_trigger_pts=3.0))
        self.assertEqual(t.exit_reason, "eod")                  # never triggered (only the data ends: last bar)

    def test_trailing_stop_in_points(self):
        rows = [(100, 100.5, 99.5, 100), (100, 100.4, 99.9, 100.3), (100.3, 103, 100.2, 102.8),
                (102.8, 102.9, 101.4, 101.6), (101.6, 101.8, 101.5, 101.7)]
        b = mk(D0, rows)
        t = one(self, trades(b, sig(5, long=[0]), trail_pts=1.5))
        # after bar 1: best 100.4 -> stop 98.9; after bar 2: best 103 -> stop 101.5; bar 3 low 101.4 -> out
        self.assertEqual((t.exit_bar, t.exit_reason, t.exit_price), (3, "stop", 101.25))
        self.assertAlmostEqual(t.gross_pts, 1.25)
        self.assertTrue(math.isnan(t.stop_price))               # no initial stop
        # with a trigger of 4 points the trail never starts
        t = one(self, trades(b, sig(5, long=[0]), trail_pts=1.5, trail_trigger_pts=4.0))
        self.assertEqual(t.exit_reason, "eod")
        # short
        rows = [(100, 100.5, 99.5, 100), (100, 100.1, 99.6, 99.7), (99.7, 99.8, 97, 97.2),
                (97.2, 98.6, 97.1, 98.4), (98.4, 98.6, 98.3, 98.5)]
        t = one(self, trades(mk(D0, rows), sig(5, short=[0]), trail_pts=1.5))
        self.assertEqual((t.exit_bar, t.exit_reason, t.exit_price), (3, "stop", 98.75))   # stop 97 + 1.5 = 98.5

    def test_trailing_stop_from_an_array_only_tightens(self):
        rows = [(100, 100.5, 99.5, 100), (100, 100.4, 99.9, 100.3), (100.3, 101.5, 100.2, 101.2),
                (101.2, 101.4, 100.8, 101), (101, 101.1, 100.4, 100.6), (100.6, 100.8, 100.5, 100.7)]
        b = mk(D0, rows)
        tr = np.array([NAN, 99.0, 100.5, 100.2, 100.2, 100.2])
        t = one(self, trades(b, sig(6, long=[0]), stop=98.0, trail_long=tr))
        # stop: 98 -> 99 (after bar 1) -> 100.5 (after bar 2) -> stays 100.5 (100.2 would loosen it);
        # bar 3 low 100.8 holds, bar 4 low 100.4 -> out at 100.5 - 1 tick
        self.assertEqual((t.exit_bar, t.exit_reason, t.exit_price), (4, "stop", 100.25))

    def test_partial_exit_at_first_target_and_stop_to_breakeven(self):
        rows = [(100, 100.5, 99.5, 100), (100, 100.4, 99.8, 100.2), (100.2, 102.5, 99.9, 102.2),
                (102.2, 102.4, 99.8, 100.1), (100.1, 100.3, 99.9, 100)]
        b = mk(D0, rows)
        t = one(self, trades(b, sig(5, long=[0]), stop=98.0, tp1_pts=2.0, target_pts=6.0))
        # half is sold at 102 in bar 2 (its low 99.9 does not matter: the stop is still 98 in that bar); the stop
        # moves to 100 at the close of bar 2; the other half is stopped at 100 - 1 tick in bar 3
        self.assertTrue(t.partial_exit)
        self.assertEqual((t.partial_price, t.partial_frac), (102.0, 0.5))
        self.assertEqual((t.exit_bar, t.exit_reason, t.exit_price), (3, "stop", 99.75))
        self.assertAlmostEqual(t.gross_pts, 0.5 * 2.0 + 0.5 * -0.25)
        self.assertAlmostEqual(t.slippage_pts, 0.125)
        self.assertAlmostEqual(t.net_pts, 0.875 - 0.75)
        # tp1_stop='keep' leaves the stop at 98; a number moves it to entry + that many points
        t = one(self, trades(b, sig(5, long=[0]), stop=98.0, tp1_pts=2.0, target_pts=6.0, tp1_stop="keep"))
        self.assertEqual(t.exit_reason, "eod")
        self.assertAlmostEqual(t.gross_pts, 0.5 * 2.0 + 0.5 * 0.0)
        t = one(self, trades(b, sig(5, long=[0]), stop=98.0, tp1_pts=2.0, target_pts=6.0, tp1_stop=1.0, tp1_frac=0.25))
        self.assertEqual((t.exit_bar, t.exit_price, t.partial_frac), (3, 100.75, 0.25))
        self.assertAlmostEqual(t.gross_pts, 0.25 * 2.0 + 0.75 * 0.75)

    def test_partial_and_final_target_in_one_bar_and_stop_priority(self):
        rows = [(100, 100.5, 99.5, 100), (100, 100.4, 99.8, 100.2), (100.2, 106.5, 100.1, 106), (106, 106.2, 105.8, 106)]
        t = one(self, trades(mk(D0, rows), sig(4, long=[0]), stop=98.0, tp1_r=1.0, target_r=3.0))
        self.assertEqual((t.exit_bar, t.exit_reason, t.exit_price), (2, "target", 106.0))
        self.assertTrue(t.partial_exit)
        self.assertAlmostEqual(t.gross_pts, 0.5 * 2.0 + 0.5 * 6.0)
        rows[2] = (100.2, 102.5, 97.9, 100)                     # stop and first target in one bar: the stop, in full
        t = one(self, trades(mk(D0, rows), sig(4, long=[0]), stop=98.0, tp1_r=1.0, target_r=3.0))
        self.assertEqual((t.exit_reason, t.exit_price), ("stop", 97.75))
        self.assertFalse(t.partial_exit)
        self.assertAlmostEqual(t.gross_pts, -2.25)

    def test_structure_errors(self):
        b = mk(D0, flat(100, 4))
        with self.assertRaises(ValueError):
            E.run(b, E.Signals(sig(4, long=[0]), stop=99.0, stop_pts=1.0))
        with self.assertRaises(ValueError):
            E.run(b, E.Signals(sig(4, long=[0]), target_r=2.0))                   # R multiple without a stop
        with self.assertRaises(ValueError):
            E.run(b, E.Signals(sig(4, long=[0]), order="stop"))                   # no price
        with self.assertRaises(ValueError):
            E.run(b, E.Signals(sig(3, long=[0])))                                 # wrong length
        with self.assertRaises(ValueError):
            E.Signals(sig(4, long=[0]), tp1_frac=1.5)
        with self.assertRaises(TypeError):
            E.run(b, "not a strategy")


# ---------------------------------------------------------------------------------------------------------------------
# 5. path (b): the per-bar callback uses the same fills
# ---------------------------------------------------------------------------------------------------------------------
class TestCallbackPath(unittest.TestCase):
    def test_market_order_with_stop_and_target(self):
        b = mk(D0, [(100, 100.5, 99.5, 100), (100, 100.5, 99.8, 100.2), (100.2, 103, 97.5, 101), (101, 101.2, 100.8, 101)])

        def on_bar(ctx):
            if ctx.i == 0:
                ctx.buy_market(stop=98.0, target=102.0)
        r = E.run(b, E.Callback(on_bar))
        t = one(self, r.trades)
        self.assertEqual(r.path, "callback")
        self.assertEqual((t.entry_bar, t.entry_price, t.exit_reason, t.exit_price), (1, 100.0, "stop", 97.75))

    def test_stop_order_entry_bar_rule_and_context_state(self):
        b = mk(D0, [(100, 100.5, 99.5, 100), (100, 103, 99.8, 102.5), (102.5, 102.6, 101.9, 102.2),
                    (102.2, 102.3, 102, 102.1)])
        seen = []

        def on_bar(ctx):
            if ctx.i == 0:
                self.assertTrue(ctx.buy_stop(101.0, stop=99.5, target=102.0))
            seen.append((ctx.i, ctx.position, ctx.entry_price, ctx.stop, ctx.target, ctx.pending_long, ctx.bars_held))
        t = one(self, E.run(b, E.Callback(on_bar)).trades)
        self.assertEqual((t.entry_price, t.exit_bar, t.exit_reason, t.exit_price), (101.25, 2, "target", 102.0))
        self.assertEqual(seen[0], (0, 0, None, None, None, False, 0))
        self.assertEqual(seen[1], (1, 1, 101.25, 99.5, 102.0, False, 1))
        self.assertEqual(seen[2][:3], (2, 0, None))

    def test_pending_flag_cancel_and_replace(self):
        rows = flat(100, 8)
        rows[5] = (100, 102, 99.9, 101.5)
        b = mk(D0, rows)
        log = []

        def on_bar(ctx):
            log.append((ctx.i, ctx.pending_long, ctx.pending_short))
            if ctx.i == 0:
                ctx.buy_stop(105.0)
                ctx.sell_stop(95.0)
            if ctx.i == 2:
                ctx.cancel(-1)
            if ctx.i == 3:
                ctx.buy_stop(101.0, max_bars=1)             # replaces the 105 order
        t = one(self, E.run(b, E.Callback(on_bar)).trades)
        self.assertEqual((t.entry_bar, t.entry_price, t.signal_bar), (5, 101.25, 3))
        self.assertEqual(log[1], (1, True, True))
        self.assertEqual(log[3], (3, True, False))

    def test_set_stop_set_target_and_exit(self):
        rows = [(100, 100.5, 99.5, 100), (100, 100.4, 99.8, 100.2), (100.2, 101.5, 100.1, 101.2),
                (101.2, 101.4, 100.4, 100.6), (100.6, 100.8, 100.5, 100.7)]
        b = mk(D0, rows)

        def trail(ctx):
            if ctx.i == 0:
                ctx.buy_market(stop=98.0)
            if ctx.position > 0 and ctx.i == 2:
                self.assertAlmostEqual(ctx.mfe, 1.5)
                self.assertAlmostEqual(ctx.open_pts, 1.2)
                self.assertAlmostEqual(ctx.risk, 2.0)
                ctx.set_stop(100.5)
        t = one(self, E.run(b, E.Callback(trail)).trades)
        self.assertEqual((t.exit_bar, t.exit_reason, t.exit_price), (3, "stop", 100.25))

        def tgt(ctx):
            if ctx.i == 0:
                ctx.buy_market()
            if ctx.i == 1:
                ctx.set_target(101.0)
        t = one(self, E.run(b, E.Callback(tgt)).trades)
        self.assertEqual((t.exit_bar, t.exit_reason, t.exit_price), (2, "target", 101.0))

        def ex(ctx):
            if ctx.i == 0:
                ctx.buy_market()
            if ctx.i == 2:
                ctx.exit()
        t = one(self, E.run(b, E.Callback(ex)).trades)
        self.assertEqual((t.exit_bar, t.exit_reason, t.exit_price, t.bars_held), (3, "signal", 101.2, 2))

    def test_reverse_and_order_while_in_position(self):
        b = mk(D0, flat(100, 8))

        def rev(ctx):
            if ctx.i == 0:
                ctx.buy_market()
            if ctx.i == 3:
                ctx.exit()
                ctx.sell_market(max_bars=1)
        tr = E.run(b, E.Callback(rev)).trades
        self.assertEqual(list(tr.direction), [1, -1])
        self.assertEqual(list(tr.entry_bar), [1, 4])
        self.assertEqual(list(tr.exit_bar), [4, 4])

        def bad(ctx):
            if ctx.i in (0, 2):
                ctx.buy_market()
        with self.assertRaises(RuntimeError):
            E.run(b, E.Callback(bad))

    def test_callback_nan_voids_and_day_counters(self):
        b = mk(D0, flat(100, 8))
        got = {}

        def on_bar(ctx):
            if ctx.i == 0:
                self.assertFalse(ctx.buy_market(stop=NAN))
                self.assertFalse(ctx.buy_stop(NAN))
            if ctx.i == 1:
                ctx.buy_market(max_bars=1)
            if ctx.i == 4:
                got["trades_today"] = ctx.trades_today
                got["net_today"] = ctx.net_today
                got["n_trades"] = ctx.n_trades
        r = E.run(b, E.Callback(on_bar))
        self.assertEqual(r.diag["void"], 2)
        self.assertEqual(len(r.trades), 1)
        self.assertEqual((got["trades_today"], got["n_trades"]), (1, 1))
        self.assertAlmostEqual(got["net_today"], -0.75)

    def test_active_mask_limits_idle_calls(self):
        b = mk(D0, flat(100, 10))
        calls = []
        act = np.zeros(10, dtype=bool)
        act[[2, 7]] = True

        def on_bar(ctx):
            calls.append(ctx.i)
            if ctx.i == 2:
                ctx.buy_market(max_bars=2)
        r = E.run(b, E.Callback(on_bar, active=act))
        self.assertEqual(calls, [2, 3, 4, 7])                  # idle bars are skipped; live bars are always called
        self.assertEqual(len(r.trades), 1)

    def test_session_rules_apply_to_callbacks(self):
        b = mk_at(LATE, flat(100, 10))

        def on_bar(ctx):
            if ctx.position == 0 and not ctx.pending_long:
                ctx.buy_market()
        tr = E.run(b, E.Callback(on_bar)).trades
        # the trade from 15:45 runs to the 16:10 flat time; orders placed at the 16:00, 16:05 and 16:10 closes cannot
        # fill (after the last-entry time); the order placed at the 16:15 close fills at the 18:00 evening open
        self.assertEqual(len(tr), 2)
        self.assertEqual((str(tr.iloc[0].entry_time), tr.iloc[0].exit_reason), ("2024-01-10 15:45:00-05:00", "eod"))
        self.assertEqual(str(tr.iloc[0].exit_time), "2024-01-10 16:10:00-05:00")
        self.assertEqual(str(tr.iloc[1].entry_time), "2024-01-10 18:00:00-05:00")


# ---------------------------------------------------------------------------------------------------------------------
# 6. calendar: DST weeks, trading-day id, incomplete days, the 16:15 cut
# ---------------------------------------------------------------------------------------------------------------------
class TestCalendar(unittest.TestCase):
    def _check_week(self, dates, change_idx, utc_before, utc_after):
        m1 = synth_1m(dates, seed=3)
        for res in (1, 5):
            b = bars_from_1m(m1, res)
            # the regular session is 09:30-16:00 New York time on every day (independent check with zoneinfo)
            for i in range(b.n):
                lt = local(b.t[i])
                mod = lt.hour * 60 + lt.minute
                self.assertEqual(bool(b.rth[i]), 570 <= mod and mod + res <= 960, (res, lt))
                self.assertEqual(int(b.mod[i]), mod)
                self.assertEqual(str(b.date[i]), lt.strftime("%Y-%m-%d"))
                self.assertEqual(int(b.wd[i]), lt.weekday())
            per_day = np.bincount(b.day_idx[b.rth], minlength=len(b.days))
            self.assertTrue((per_day == 390 // res).all())
            # the first regular-session bar is 14:30 UTC in winter time and 13:30 UTC in summer time
            for k, row in b.days.iterrows():
                u = datetime.fromtimestamp(int(b.t[row.rth_first]), ZoneInfo("UTC"))
                want = utc_before if k < change_idx else utc_after
                self.assertEqual((u.hour, u.minute), want, (res, row.date))
                self.assertEqual(int(row.rth_first_mod), 570)
            self.assertTrue(b.days.complete.all())
            # an entry at the session open is filled at 09:30 ET and closed at 16:10 ET on every day
            go = np.zeros(b.n, dtype=int)
            go[b.days.rth_first.to_numpy() - 1] = 1
            tr = E.run(b, E.Signals(go)).trades
            self.assertEqual(len(tr), len(dates))
            for t in tr.itertuples():
                self.assertEqual((t.entry_time.hour, t.entry_time.minute), (9, 30))
                self.assertEqual((t.exit_time.hour, t.exit_time.minute), (16, 10))
                self.assertEqual(t.exit_reason, "eod")
            offs = sorted({int(x.utcoffset().total_seconds()) // 3600 for x in tr.entry_time})
            self.assertEqual(offs, [-5, -4])                     # both clocks occur in the week

    def test_dst_week_march(self):
        # US clocks go forward on Sunday 2024-03-10
        self._check_week(["2024-03-07", "2024-03-08", "2024-03-11", "2024-03-12"], 2, (14, 30), (13, 30))

    def test_dst_week_november(self):
        # US clocks go back on Sunday 2024-11-03
        self._check_week(["2024-10-31", "2024-11-01", "2024-11-04", "2024-11-05"], 2, (13, 30), (14, 30))

    def test_trading_day_id_across_midnight_and_sunday_open(self):
        times = ["2024-01-12 16:10", "2024-01-14 18:00", "2024-01-14 23:55", "2024-01-15 00:00", "2024-01-15 09:30",
                 "2024-01-15 16:10", "2024-01-15 18:00", "2024-01-16 09:30"]
        b = mk_at(times, flat(100, 8))
        self.assertEqual([str(x) for x in b.tday], ["2024-01-12", "2024-01-15", "2024-01-15", "2024-01-15",
                                                    "2024-01-15", "2024-01-15", "2024-01-16", "2024-01-16"])
        self.assertEqual([str(x) for x in b.date], ["2024-01-12", "2024-01-14", "2024-01-14", "2024-01-15",
                                                    "2024-01-15", "2024-01-15", "2024-01-15", "2024-01-16"])
        self.assertEqual(list(b.wd), [4, 6, 6, 0, 0, 0, 0, 1])          # Friday, Sunday, Sunday, Monday ...
        self.assertEqual(list(b.tday_wd), [4, 0, 0, 0, 0, 0, 1, 1])
        self.assertEqual(list(b.day_idx), [0, 1, 1, 1, 1, 1, 2, 2])
        self.assertEqual(list(b.tmin), [1330, 0, 355, 360, 930, 1330, 0, 930])
        self.assertEqual(list(b.mod), [970, 1080, 1435, 0, 570, 970, 1080, 570])
        self.assertEqual(list(b.rth), [False, False, False, False, True, False, False, True])
        ids = b.tday_id
        self.assertEqual(int(ids[1]), int(ids[4]))             # Sunday 18:00 and Monday 09:30: the same trading day
        self.assertEqual(int(ids[2]), int(ids[3]))             # 23:55 and 00:00: the same trading day
        self.assertEqual(int(ids[6]) - int(ids[5]), 1)         # 18:00 starts the next trading day
        self.assertEqual(int(ids[1]) - int(ids[0]), 3)         # Friday -> Monday
        self.assertEqual(list(b.days.date.astype(str)), ["2024-01-12", "2024-01-15", "2024-01-16"])
        self.assertEqual(E.tmin_of("18:00"), 0)
        self.assertEqual(E.tmin_of("09:30"), 930)
        self.assertEqual(E.tmin_of("16:10"), E.TMIN_FLAT)
        self.assertEqual(E.hm("16:15"), E.MOD_DAY_END)

    def test_bars_after_1615_are_rejected_and_dropped(self):
        with self.assertRaises(ValueError):
            mk_at(["2024-01-10 16:10", "2024-01-10 16:15"], flat(100, 2))
        with self.assertRaises(ValueError):
            mk_at(["2024-01-10 16:10", "2024-01-10 17:55"], flat(100, 2))
        mk_at(["2024-01-10 16:10", "2024-01-10 18:00"], flat(100, 2))          # fine
        # the resampler drops 1-minute bars from 16:15 to 17:59
        t = np.array([ep("2024-01-10 16:13"), ep("2024-01-10 16:14"), ep("2024-01-10 16:15"), ep("2024-01-10 16:30"),
                      ep("2024-01-10 17:59"), ep("2024-01-10 18:00")])
        p = np.array([1.0, 2, 3, 4, 5, 6])
        r = E.resample_1m(t, p, p, p, p, 5)
        self.assertEqual(list(r["t"]), [ep("2024-01-10 16:10"), ep("2024-01-10 18:00")])
        self.assertEqual(list(r["c"]), [2.0, 6.0])

    def test_time_between(self):
        times = ["2024-01-09 18:00", "2024-01-09 23:55", "2024-01-10 09:25", "2024-01-10 09:30", "2024-01-10 10:55",
                 "2024-01-10 11:00", "2024-01-10 16:10"]
        b = mk_at(times, flat(100, 7))
        self.assertEqual(list(b.time_between("09:30", "11:00")), [False, False, False, True, True, False, False])
        self.assertEqual(list(b.time_between("18:00", "09:30")), [True, True, True, False, False, False, False])
        self.assertEqual(list(b.time_between("11:00", "16:15")), [False, False, False, False, False, True, True])
        self.assertEqual(list(b.opens_at("09:30")), [False, False, False, True, False, False, False])
        self.assertEqual(list(b.ends_at("09:30")), [False, False, True, False, False, False, False])
        self.assertEqual(list(b.ends_at("16:15")), [False, False, False, False, False, False, True])

    def test_incomplete_day_exclusion(self):
        # day A has 369 regular-session 1-minute bars (incomplete), day B has 370 (complete), day C all 390
        def drop(ds, mod):
            if ds == "2024-01-09":
                return 600 <= mod < 621          # 21 minutes missing -> 369
            if ds == "2024-01-10":
                return 600 <= mod < 620          # 20 minutes missing -> 370
            return False
        m1 = synth_1m(["2024-01-09", "2024-01-10", "2024-01-11"], seed=5, drop=drop)
        ids, cnt = E.rth_counts(m1[0])
        self.assertEqual(list(cnt), [369, 370, 390])
        for res in (1, 5, 15):
            b = bars_from_1m(m1, res)
            self.assertEqual(list(b.days.n_rth_1m), [369, 370, 390])
            self.assertEqual(list(b.days.complete), [False, True, True])
            # the flag covers the whole trading day (also its evening session) at every resolution
            self.assertTrue(b.incomplete[b.day_idx == 0].all())
            self.assertFalse(b.incomplete[b.day_idx > 0].any())
            # signals on every bar: no entry is ever filled on the incomplete day
            tr = E.run(b, E.Signals(np.ones(b.n, dtype=int), max_bars=3)).trades
            self.assertGreater(len(tr), 50)
            self.assertEqual(sorted(set(tr.entry_day.dt.strftime("%Y-%m-%d"))), ["2024-01-10", "2024-01-11"])
            tr = E.run(b, E.Signals(np.ones(b.n, dtype=int), order="stop", price=b.h + 0.25, expiry_bars=2,
                                    max_bars=3, allow_multi_day=True)).trades
            self.assertGreater(len(tr), 20)
            self.assertNotIn("2024-01-09", set(tr.entry_day.dt.strftime("%Y-%m-%d")))
        # explicit per-bar flags work the same way
        b = mk(D0, flat(100, 6), incomplete=np.ones(6, dtype=bool))
        self.assertEqual(len(trades(b, sig(6, long=[0, 1, 2]))), 0)

    def test_truncate_keeps_flags(self):
        m1 = synth_1m(["2024-01-09", "2024-01-10"], seed=6, drop=lambda ds, mod: ds == "2024-01-09" and mod >= 700)
        b = bars_from_1m(m1, 5)
        tb = b.truncate(300)
        self.assertEqual(tb.n, 300)
        self.assertTrue((tb.incomplete == b.incomplete[:300]).all())
        self.assertTrue((tb.t == b.t[:300]).all())
        self.assertTrue((tb.tmin_end == b.tmin_end[:300]).all())


# ---------------------------------------------------------------------------------------------------------------------
# 7. resampling
# ---------------------------------------------------------------------------------------------------------------------
def ref_resample(m1, n_min, anchor=0):
    """Loop reference: group 1-minute bars by (trading day, clock bucket)."""
    t, o, h, l, c = m1
    out = {}
    order = []
    for i in range(len(t)):
        lt = local(t[i])
        mod = lt.hour * 60 + lt.minute
        if 975 <= mod < 1080:
            continue
        b = ((mod - anchor) // n_min) * n_min + anchor
        if mod >= 1080 and b < 1080:
            b = 1080
        key = int(t[i]) - (mod - b) * 60
        if key not in out:
            out[key] = [o[i], h[i], l[i], c[i]]
            order.append(key)
        else:
            r = out[key]
            r[1] = max(r[1], h[i]); r[2] = min(r[2], l[i]); r[3] = c[i]
    return np.array(order), np.array([out[k] for k in order])


class TestResampling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m1 = synth_1m(["2024-03-08", "2024-03-11", "2024-03-12"], seed=11,
                          drop=lambda ds, mod: ds == "2024-03-11" and 700 <= mod < 707)

    def test_against_loop_reference(self):
        for n_min, anchor in ((5, 0), (15, 0), (30, 0), (60, 0), (60, 30), (7, 0), (240, 0), (3, 0)):
            r = E.resample_1m(*self.m1, n_min, f"{anchor // 60:02d}:{anchor % 60:02d}")
            keys, ohlc = ref_resample(self.m1, n_min, anchor)
            self.assertTrue(np.array_equal(r["t"], keys), n_min)
            got = np.column_stack([r["o"], r["h"], r["l"], r["c"]])
            self.assertTrue(np.array_equal(got, ohlc), n_min)

    def test_buckets_are_aligned_to_the_new_york_clock(self):
        r = E.resample_1m(*self.m1, 15)
        for t in r["t"]:
            self.assertEqual(local(t).minute % 15, 0)
        r = E.resample_1m(*self.m1, 60, "09:30")
        mins = {local(t).minute for t in r["t"]}
        self.assertEqual(mins, {0, 30})                          # 18:00 evening bar (forced) and the :30 buckets
        b = bars_from_1m(self.m1, 60, "09:30")
        first_rth = [local(b.t[i]).strftime("%H:%M") for i in b.days.rth_first]
        self.assertEqual(first_rth, ["09:30"] * 3)

    def test_five_minute_bar_content(self):
        t, o, h, l, c = self.m1
        r = E.resample_1m(t, o, h, l, c, 5)
        k = int(np.flatnonzero(r["t"] == ep("2024-03-12 10:05"))[0])
        m = (t >= ep("2024-03-12 10:05")) & (t < ep("2024-03-12 10:10"))
        self.assertEqual(int(m.sum()), 5)
        self.assertEqual(r["o"][k], o[m][0])
        self.assertEqual(r["h"][k], h[m].max())
        self.assertEqual(r["l"][k], l[m].min())
        self.assertEqual(r["c"][k], c[m][-1])

    def test_nominal_bar_end_and_break(self):
        b = bars_from_1m(self.m1, 30)
        i = int(np.flatnonzero(b.t == ep("2024-03-12 16:00"))[0])
        self.assertEqual(int(b.tmin_end[i]), E.TMIN_DAY_END)     # the 16:00-16:30 bucket is cut at 16:15
        self.assertEqual(int(b.t_end[i]), ep("2024-03-12 16:15"))
        self.assertFalse(b.rth[i])
        self.assertEqual(int(b.end_mod[i]), 975)
        # a 240-minute bucket 16:00-20:00 is split at the break: afternoon part and an 18:00 evening bar
        r = E.resample_1m(*self.m1, 240)
        hhmm = [local(x).strftime("%d %H:%M") for x in r["t"]]
        self.assertIn("11 16:00", hhmm)
        self.assertIn("11 18:00", hhmm)
        k = hhmm.index("11 18:00")
        self.assertEqual(int(r["tmin_end"][k]), 120)             # nominal end 20:00
        b = bars_from_1m(self.m1, 240)
        self.assertEqual(str(b.tday[k]), "2024-03-12")

    @unittest.skipUnless(HAVE_DATA, "data files not found")
    def test_real_data_1m_to_5m_equals_the_5m_file_and_nothing_after_1615(self):
        b5 = E.load_bars(5)
        raw = E._load_npz(E.FILE_1M)
        r = E.resample_1m(raw["t"], raw["o"], raw["h"], raw["l"], raw["c"], 5)
        self.assertTrue(np.array_equal(r["t"], b5.t))
        for k in "ohlc":
            self.assertTrue(np.array_equal(r[k], getattr(b5, k)), k)
        self.assertTrue(np.array_equal(r["tmin_end"], b5.tmin_end))
        self.assertFalse(((b5.mod >= 975) & (b5.mod < 1080)).any())
        self.assertLessEqual(int(b5.tmin_end.max()), E.TMIN_DAY_END)
        b15 = E.load_bars(15)
        self.assertFalse(((b15.mod >= 975) & (b15.mod < 1080)).any())
        self.assertTrue(np.array_equal(b15.days.complete.to_numpy(), b5.days.complete.to_numpy()))
        # spot-check the New York clock of the real bars with zoneinfo (random bars, all years)
        rng = np.random.default_rng(0)
        for i in rng.integers(0, b5.n, 400):
            lt = local(b5.t[i])
            self.assertEqual(int(b5.mod[i]), lt.hour * 60 + lt.minute)
            self.assertEqual(str(b5.date[i]), lt.strftime("%Y-%m-%d"))
        # the first regular-session bar of every complete day opens at 09:30 New York time
        d = b5.days[b5.days.complete]
        self.assertTrue((d.rth_first_mod == 570).mean() > 0.995)
        self.assertEqual(int(d.complete.sum()), E.N_COMPLETE_DAYS)


# ---------------------------------------------------------------------------------------------------------------------
# 8. indicators against independent references (plain loops / pandas)
# ---------------------------------------------------------------------------------------------------------------------
def close_enough(tc, got, want, tol=1e-9, msg=""):
    got = np.asarray(got, dtype="float64")
    want = np.asarray(want, dtype="float64")
    tc.assertEqual(got.shape, want.shape, msg)
    tc.assertTrue(np.array_equal(np.isnan(got), np.isnan(want)), f"{msg}: NaN pattern differs")
    m = ~np.isnan(want)
    if m.any():
        tc.assertLess(float(np.max(np.abs(got[m] - want[m]))), tol, msg)


def ref_wilder(x, n):
    out = [NAN] * len(x)
    f = next((i for i, v in enumerate(x) if v == v), None)
    if f is None or len(x) - f < n:
        return out
    y = sum(x[f:f + n]) / n
    out[f + n - 1] = y
    for i in range(f + n, len(x)):
        y = y + (x[i] - y) / n
        out[i] = y
    return out


def ref_tr(h, l, c):
    out = [h[0] - l[0]]
    for i in range(1, len(h)):
        out.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    return out


class TestIndicatorsSeries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(42)
        n = 400
        c = 15000 + np.cumsum(rng.normal(0, 5, n))
        o = np.r_[c[0], c[:-1]] + rng.normal(0, 1, n)
        cls.h = np.maximum(o, c) + np.abs(rng.normal(0, 2, n))
        cls.l = np.minimum(o, c) - np.abs(rng.normal(0, 2, n))
        cls.c = c
        cls.n = n

    def test_sma_std_max_min(self):
        c, n = self.c, self.n
        for w in (1, 5, 20):
            want = [NAN if i < w - 1 else float(np.mean(c[i - w + 1:i + 1])) for i in range(n)]
            close_enough(self, E.sma(c, w), want, 1e-8, "sma")
            want = [NAN if i < w - 1 else float(np.std(c[i - w + 1:i + 1])) for i in range(n)]
            close_enough(self, E.rolling_std(c, w), want, 1e-6, "std")
            want = [NAN if i < w - 1 else float(np.max(c[i - w + 1:i + 1])) for i in range(n)]
            close_enough(self, E.rolling_max(c, w), want, 1e-12, "max")
            want = [NAN if i < w - 1 else float(np.min(c[i - w + 1:i + 1])) for i in range(n)]
            close_enough(self, E.rolling_min(c, w), want, 1e-12, "min")
        want = [NAN if i < 19 else float(np.std(c[i - 19:i + 1], ddof=1)) for i in range(n)]
        close_enough(self, E.rolling_std(c, 20, ddof=1), want, 1e-6, "std ddof=1")

    def test_ema(self):
        c = self.c
        for w in (3, 20):
            a = 2.0 / (w + 1)
            y = c[0]
            want = [y]
            for i in range(1, self.n):
                y = a * c[i] + (1 - a) * y
                want.append(y)
            want = [NAN if i < w - 1 else v for i, v in enumerate(want)]
            close_enough(self, E.ema(c, w), want, 1e-8, "ema loop")
            pdv = pd.Series(c).ewm(span=w, adjust=False, min_periods=w).mean().to_numpy()
            close_enough(self, E.ema(c, w), pdv, 1e-8, "ema pandas")
        # leading NaNs are skipped
        x = np.r_[[NAN] * 7, c[:50]]
        close_enough(self, E.ema(x, 5), pd.Series(x).ewm(span=5, adjust=False, min_periods=5).mean().to_numpy(), 1e-8)

    def test_wilder_true_range_atr(self):
        h, l, c = self.h, self.l, self.c
        close_enough(self, E.true_range(h, l, c), ref_tr(h, l, c), 1e-12, "tr")
        for w in (5, 14):
            close_enough(self, E.wilder(c, w), ref_wilder(list(c), w), 1e-8, "wilder")
            close_enough(self, E.atr(h, l, c, w), ref_wilder(ref_tr(h, l, c), w), 1e-8, "atr")

    def test_rsi(self):
        c = self.c
        for w in (2, 14):
            want = [NAN] * self.n
            g = [max(c[i] - c[i - 1], 0.0) for i in range(1, self.n)]
            d = [max(c[i - 1] - c[i], 0.0) for i in range(1, self.n)]
            ag = sum(g[:w]) / w
            ad = sum(d[:w]) / w
            for i in range(w, self.n):
                if i > w:
                    ag = (ag * (w - 1) + g[i - 1]) / w
                    ad = (ad * (w - 1) + d[i - 1]) / w
                want[i] = 100.0 if ad == 0 else 100.0 - 100.0 / (1.0 + ag / ad)
            close_enough(self, E.rsi(c, w), want, 1e-8, "rsi")
        up = np.arange(1.0, 40.0)
        self.assertEqual(E.rsi(up, 5)[-1], 100.0)               # only gains
        self.assertEqual(E.rsi(np.full(30, 7.0), 5)[-1], 50.0)  # no movement

    def test_adx(self):
        h, l, c, n = self.h, self.l, self.c, self.n
        for w in (5, 14):
            pdm = [NAN]; mdm = [NAN]
            for i in range(1, n):
                up = h[i] - h[i - 1]
                dn = l[i - 1] - l[i]
                pdm.append(up if (up > dn and up > 0) else 0.0)
                mdm.append(dn if (dn > up and dn > 0) else 0.0)
            tr = ref_tr(h, l, c)
            tr[0] = NAN
            s_tr, s_p, s_m = ref_wilder(tr, w), ref_wilder(pdm, w), ref_wilder(mdm, w)
            pdi = [NAN if s_tr[i] != s_tr[i] else 100 * s_p[i] / s_tr[i] for i in range(n)]
            mdi = [NAN if s_tr[i] != s_tr[i] else 100 * s_m[i] / s_tr[i] for i in range(n)]
            dx = [NAN if pdi[i] != pdi[i] else (0.0 if pdi[i] + mdi[i] == 0 else 100 * abs(pdi[i] - mdi[i]) / (pdi[i] + mdi[i]))
                  for i in range(n)]
            want = ref_wilder(dx, w)
            a, p, m = E.adx(h, l, c, w)
            close_enough(self, p, pdi, 1e-8, "+DI")
            close_enough(self, m, mdi, 1e-8, "-DI")
            close_enough(self, a, want, 1e-8, "adx")
            self.assertTrue(np.isnan(a[2 * w - 2]) and not np.isnan(a[2 * w - 1]))

    def test_bollinger_keltner_donchian(self):
        h, l, c, n = self.h, self.l, self.c, self.n
        mid, up, lo = E.bollinger(c, 20, 2.5)
        m_ref = [NAN if i < 19 else float(np.mean(c[i - 19:i + 1])) for i in range(n)]
        s_ref = [NAN if i < 19 else float(np.std(c[i - 19:i + 1])) for i in range(n)]
        close_enough(self, mid, m_ref, 1e-8)
        close_enough(self, up, np.array(m_ref) + 2.5 * np.array(s_ref), 1e-6)
        close_enough(self, lo, np.array(m_ref) - 2.5 * np.array(s_ref), 1e-6)
        kmid, kup, klo = E.keltner(h, l, c, 20, 10, 1.5)
        e_ref = pd.Series(c).ewm(span=20, adjust=False, min_periods=20).mean().to_numpy()
        a_ref = np.array(ref_wilder(ref_tr(h, l, c), 10))
        close_enough(self, kmid, e_ref, 1e-8)
        close_enough(self, kup, e_ref + 1.5 * a_ref, 1e-8)
        close_enough(self, klo, e_ref - 1.5 * a_ref, 1e-8)
        for w in (1, 10):
            dh, dl = E.donchian(h, l, w)
            close_enough(self, dh, [NAN if i < w - 1 else max(h[i - w + 1:i + 1]) for i in range(n)], 1e-12)
            close_enough(self, dl, [NAN if i < w - 1 else min(l[i - w + 1:i + 1]) for i in range(n)], 1e-12)
            dh, dl = E.donchian(h, l, w, include_current=False)
            close_enough(self, dh, [NAN if i < w else max(h[i - w:i]) for i in range(n)], 1e-12)
            close_enough(self, dl, [NAN if i < w else min(l[i - w:i]) for i in range(n)], 1e-12)

    def test_lag_cross_masked(self):
        x = np.array([1.0, 2, 3, 4])
        close_enough(self, E.lag(x, 2), [NAN, NAN, 1, 2])
        with self.assertRaises(ValueError):
            E.lag(x, -1)
        a = np.array([1.0, 1, 3, 3, 1, 2, 2])
        b = np.full(7, 2.0)
        self.assertEqual(list(E.cross_above(a, b)), [False, False, True, False, False, False, False])
        self.assertEqual(list(E.cross_below(a, b)), [False, False, False, False, True, False, False])
        m = np.array([True, False, True, True, False, True])
        v = np.array([1.0, 100, 2, 3, 100, 4])
        close_enough(self, E.masked(m, lambda z: E.sma(z, 2), v), [NAN, NAN, 1.5, 2.5, NAN, 3.5])
        close_enough(self, E.masked(m, lambda z: E.sma(z, 2), v, ffill=True), [NAN, NAN, 1.5, 2.5, 2.5, 3.5])

    def test_no_lookahead_in_series_indicators(self):
        # changing the future must not change the past
        h, l, c = self.h.copy(), self.l.copy(), self.c.copy()
        k = 250
        fns = {
            "sma": lambda: E.sma(c, 20), "ema": lambda: E.ema(c, 20), "atr": lambda: E.atr(h, l, c, 14),
            "rsi": lambda: E.rsi(c, 14), "adx": lambda: E.adx(h, l, c, 14)[0], "boll": lambda: E.bollinger(c, 20)[1],
            "kelt": lambda: E.keltner(h, l, c)[2], "don": lambda: E.donchian(h, l, 20)[0],
            "don_x": lambda: E.donchian(h, l, 20, False)[1], "std": lambda: E.rolling_std(c, 20),
        }
        before = {name: f()[:k].copy() for name, f in fns.items()}
        h[k:] += 500.0; l[k:] -= 500.0; c[k:] += 123.0
        for name, f in fns.items():
            self.assertTrue(np.array_equal(f()[:k], before[name], equal_nan=True), name)


class TestIndicatorsSession(unittest.TestCase):
    """Session helpers against loop references on synthetic 5-minute bars (9 trading days around a weekend)."""
    DATES = ["2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11", "2024-01-12", "2024-01-15", "2024-01-16",
             "2024-01-17", "2024-01-18"]

    @classmethod
    def setUpClass(cls):
        def drop(ds, mod):
            if ds == "2024-01-10":
                return mod >= 13 * 60                    # a half day: the regular session ends at 13:00 (incomplete)
            if ds == "2024-01-12":
                return 575 <= mod < 580                  # one 5-minute bar of the opening range is missing
            if ds == "2024-01-16":
                return 570 <= mod < 585                  # the session's first three 5-minute bars are missing
            return False
        cls.m1 = synth_1m(cls.DATES, seed=21, drop=drop)
        cls.b = bars_from_1m(cls.m1, 5)
        b = cls.b
        # an independent description of every bar (zoneinfo)
        cls.info = []
        for i in range(b.n):
            lt = local(b.t[i])
            mod = lt.hour * 60 + lt.minute
            td = (lt + timedelta(days=1)).strftime("%Y-%m-%d") if mod >= 1080 else lt.strftime("%Y-%m-%d")
            cls.info.append((td, mod, (mod - 1080) % 1440))
        cls.days = sorted({x[0] for x in cls.info})
        cls.by_day = {d: [i for i in range(b.n) if cls.info[i][0] == d] for d in cls.days}
        cls.rth_idx = {d: [i for i in cls.by_day[d] if 570 <= cls.info[i][1] and cls.info[i][1] + 5 <= 960]
                       for d in cls.days}
        cnt = {}
        for t in cls.m1[0]:
            lt = local(t)
            mod = lt.hour * 60 + lt.minute
            if 570 <= mod < 960:
                cnt[lt.strftime("%Y-%m-%d")] = cnt.get(lt.strftime("%Y-%m-%d"), 0) + 1
        cls.complete = {d: cnt.get(d, 0) >= 370 for d in cls.days}

    def prior(self, d, require_complete=True):
        """(open, high, low, close) of the prior regular session of trading day d, by loop."""
        b = self.b
        k = self.days.index(d)
        while k > 0:
            k -= 1
            p = self.days[k]
            idx = self.rth_idx[p]
            if idx:
                if require_complete and not self.complete[p]:
                    return (NAN,) * 4
                return (b.o[idx[0]], max(b.h[idx]), min(b.l[idx]), b.c[idx[-1]])
        return (NAN,) * 4

    def test_day_table(self):
        b = self.b
        self.assertEqual(list(b.days.date.astype(str)), self.days)
        self.assertEqual(list(b.days.complete), [self.complete[d] for d in self.days])
        self.assertEqual([d for d in self.days if not self.complete[d]], ["2024-01-10"])
        for k, d in enumerate(self.days):
            idx = self.rth_idx[d]
            row = b.days.iloc[k]
            self.assertEqual((row["first"], row["last"]), (self.by_day[d][0], self.by_day[d][-1]))
            self.assertEqual((row.rth_first, row.rth_last), (idx[0], idx[-1]))
            self.assertEqual((row.rth_open, row.rth_high, row.rth_low, row.rth_close),
                             (b.o[idx[0]], max(b.h[idx]), min(b.l[idx]), b.c[idx[-1]]))

    def test_prior_rth(self):
        b = self.b
        for rc in (True, False):
            got = E.prior_rth(b, require_complete=rc)
            want = np.array([self.prior(self.info[i][0], rc) for i in range(b.n)])
            for j, k in enumerate(("open", "high", "low", "close")):
                close_enough(self, got[k], want[:, j], 1e-12, f"prior {k} rc={rc}")
        # the day after the half day has NaN levels by default, real ones with require_complete=False
        i = self.by_day["2024-01-11"][0]
        self.assertTrue(np.isnan(E.prior_rth(b)["high"][i]))
        self.assertFalse(np.isnan(E.prior_rth(b, require_complete=False)["high"][i]))
        # constant over the whole trading day, from the 18:00 evening open
        ph = E.prior_rth(b)["high"]
        for d in self.days[1:]:
            v = ph[self.by_day[d]]
            self.assertTrue(np.all(np.isnan(v)) or np.all(v == v[0]))

    def test_overnight_range(self):
        b = self.b
        hi, lo = E.overnight_range(b)
        wh, wl = [], []
        for i in range(b.n):
            d = self.info[i][0]
            idx = [j for j in self.by_day[d] if j <= i and self.info[j][2] < 930]
            wh.append(max(b.h[idx]) if idx else NAN)
            wl.append(min(b.l[idx]) if idx else NAN)
        close_enough(self, hi, wh, 1e-12, "overnight high")
        close_enough(self, lo, wl, 1e-12, "overnight low")

    def test_session_high_low(self):
        b = self.b
        hi, lo = E.session_high_low(b, "09:30")
        wh, wl = [], []
        for i in range(b.n):
            d = self.info[i][0]
            idx = [j for j in self.by_day[d] if j <= i and self.info[j][2] >= 930]
            wh.append(max(b.h[idx]) if idx else NAN)
            wl.append(min(b.l[idx]) if idx else NAN)
        close_enough(self, hi, wh, 1e-12)
        close_enough(self, lo, wl, 1e-12)

    def test_opening_range(self):
        b = self.b
        for start, minutes, full in (("09:30", 30, True), ("09:30", 15, True), ("09:30", 30, False), ("08:00", 60, True),
                                     ("18:00", 30, True)):
            a = E.tmin_of(start)
            hi, lo = E.opening_range(b, start, minutes, require_full=full)
            wh, wl = [], []
            for i in range(b.n):
                d = self.info[i][0]
                win = [j for j in self.by_day[d] if self.info[j][2] >= a and self.info[j][2] + 5 <= a + minutes]
                ok = bool(win) and (not full or len(win) == minutes // 5) and self.info[i][2] + 5 >= a + minutes
                wh.append(max(b.h[win]) if ok else NAN)
                wl.append(min(b.l[win]) if ok else NAN)
            close_enough(self, hi, wh, 1e-12, f"OR high {start} {minutes} {full}")
            close_enough(self, lo, wl, 1e-12, f"OR low {start} {minutes} {full}")
        hi, _ = E.opening_range(b, "09:30", 30)
        day = "2024-01-09"
        idx = self.by_day[day]
        first_ok = next(i for i in idx if not np.isnan(hi[i]))
        self.assertEqual(self.info[first_ok][1], 9 * 60 + 55)     # appears on the bar that completes the window
        self.assertTrue(np.all(np.isnan(hi[self.by_day["2024-01-12"]])))     # a window bar is missing: NaN all day
        self.assertFalse(np.all(np.isnan(E.opening_range(b, "09:30", 30, require_full=False)[0][self.by_day["2024-01-12"]])))

    def test_rth_open_and_gap(self):
        b = self.b
        for late in (5, 30):
            want_o, want_g, want_gp = [], [], []
            for i in range(b.n):
                d = self.info[i][0]
                idx = self.rth_idx[d]
                if idx and i >= idx[0] and self.info[idx[0]][1] <= 570 + late:
                    ro = b.o[idx[0]]
                else:
                    ro = NAN
                pc = self.prior(d)[3]
                want_o.append(ro)
                want_g.append(ro - pc)
                want_gp.append((ro - pc) / pc)
            close_enough(self, E.rth_open(b, max_late_min=late), want_o, 1e-12, "rth open")
            close_enough(self, E.gap(b, max_late_min=late), want_g, 1e-9, "gap")
            close_enough(self, E.gap(b, pct=True, max_late_min=late), want_gp, 1e-12, "gap pct")
        # the day whose first bars are missing has no open with the default tolerance of 5 minutes
        self.assertTrue(np.all(np.isnan(E.rth_open(b)[self.by_day["2024-01-16"]])))
        self.assertFalse(np.all(np.isnan(E.rth_open(b, 30)[self.by_day["2024-01-16"]])))

    def test_pivots(self):
        b = self.b
        fp = E.floor_pivots(b)
        cp = E.camarilla_pivots(b)
        want = {k: [] for k in ("P", "R1", "S1", "R2", "S2", "R3", "S3")}
        wc = {k: [] for k in ("R1", "R2", "R3", "R4", "S1", "S2", "S3", "S4")}
        for i in range(b.n):
            _, H, L, C = self.prior(self.info[i][0])
            P = (H + L + C) / 3
            for k, v in (("P", P), ("R1", 2 * P - L), ("S1", 2 * P - H), ("R2", P + H - L), ("S2", P - (H - L)),
                         ("R3", H + 2 * (P - L)), ("S3", L - 2 * (H - P))):
                want[k].append(v)
            for k, div in ((1, 12), (2, 6), (3, 4), (4, 2)):
                wc[f"R{k}"].append(C + (H - L) * 1.1 / div)
                wc[f"S{k}"].append(C - (H - L) * 1.1 / div)
        for k in want:
            close_enough(self, fp[k], want[k], 1e-9, f"floor {k}")
        for k in wc:
            close_enough(self, cp[k], wc[k], 1e-9, f"camarilla {k}")

    def test_daily_atr(self):
        b = self.b
        comp = [d for d in self.days if self.complete[d] and self.rth_idx[d]]
        H = [max(b.h[self.rth_idx[d]]) for d in comp]
        L = [min(b.l[self.rth_idx[d]]) for d in comp]
        C = [b.c[self.rth_idx[d][-1]] for d in comp]
        tr = ref_tr(H, L, C)
        for n, method in ((3, "wilder"), (2, "sma")):
            if method == "wilder":
                a = ref_wilder(tr, n)
            else:
                a = [NAN if i < n - 1 else sum(tr[i - n + 1:i + 1]) / n for i in range(len(tr))]
            val = dict(zip(comp, a))
            want = []
            for i in range(b.n):
                d = self.info[i][0]
                earlier = [x for x in comp if x < d]
                want.append(val[earlier[-1]] if earlier else NAN)
            close_enough(self, E.daily_atr(b, n, method), want, 1e-9, f"daily atr {method}")

    def test_twap_vwap_proxy(self):
        b = self.b
        tp = (b.h + b.l + b.c) / 3
        for anchor in ("09:30", "18:00"):
            a = E.tmin_of(anchor)
            wm, ws = [], []
            for i in range(b.n):
                d = self.info[i][0]
                idx = [j for j in self.by_day[d] if j <= i and self.info[j][2] >= a]
                if idx and self.info[i][2] >= a:
                    wm.append(float(np.mean(tp[idx])))
                    ws.append(float(np.std(tp[idx])))
                else:
                    wm.append(NAN); ws.append(NAN)
            close_enough(self, E.twap_vwap_proxy(b, anchor), wm, 1e-8, "twap")
            tw, sd = E.twap_vwap_proxy(b, anchor, bands=True)
            close_enough(self, tw, wm, 1e-8, "twap")
            close_enough(self, sd, ws, 1e-6, "twap sd")

    def test_lag_days_to_bars(self):
        b = self.b
        per_day = np.arange(len(b.days), dtype="float64") * 10
        got = E.lag_days_to_bars(b, per_day)
        want = [NAN if self.days.index(self.info[i][0]) == 0 else (self.days.index(self.info[i][0]) - 1) * 10.0
                for i in range(b.n)]
        close_enough(self, got, want, 1e-12)
        with self.assertRaises(ValueError):
            E.lag_days_to_bars(b, per_day[:-1])

    def test_session_helpers_do_not_look_ahead(self):
        b = self.b
        fns = {
            "prior": lambda x: E.prior_rth(x)["close"], "overnight": lambda x: E.overnight_range(x)[0],
            "or": lambda x: E.opening_range(x, "09:30", 30)[1], "open": lambda x: E.rth_open(x), "gap": lambda x: E.gap(x),
            "floor": lambda x: E.floor_pivots(x)["R2"], "cam": lambda x: E.camarilla_pivots(x)["S3"],
            "datr": lambda x: E.daily_atr(x, 3), "twap": lambda x: E.twap_vwap_proxy(x, "09:30"),
            "twsd": lambda x: E.twap_vwap_proxy(x, "09:30", True)[1], "hl": lambda x: E.session_high_low(x)[0],
        }
        full = {k: f(b) for k, f in fns.items()}
        for k_cut in (517, 1111, 1500, b.n - 37):
            tb = b.truncate(k_cut)
            for name, f in fns.items():
                self.assertTrue(np.array_equal(f(tb), full[name][:k_cut], equal_nan=True), (name, k_cut))


# ---------------------------------------------------------------------------------------------------------------------
# 9. the fixed split and the statistics
# ---------------------------------------------------------------------------------------------------------------------
def hand_trades():
    """Eight hand-written trades around the split date."""
    days = ["2019-05-01", "2019-05-01", "2019-05-02", "2020-03-17", "2020-03-18", "2021-06-01", "2021-06-01", "2022-01-03"]
    net = [2.0, -1.0, 3.0, -2.0, 1.0, 1.5, -0.5, 4.0]
    risk = [2.0, 2.0, NAN, 4.0, 1.0, 3.0, 1.0, NAN]
    df = pd.DataFrame({
        "entry_day": pd.to_datetime(days), "net_pts": net, "gross_pts": [x + 0.75 for x in net],
        "risk_pts": risk, "r_multiple": [n_ / r for n_, r in zip(net, risk)],
        "mae_pts": [1.0, 3.0, 0.5, 4.0, 0.0, 2.0, 2.5, 1.5], "minutes_held": [5.0, 10, 15, 20, 25, 30, 35, 400],
    })
    df["split"] = np.where(df.entry_day >= pd.Timestamp(E.SPLIT_DATE), "OOS", "IS")
    return df


class TestSplitAndStats(unittest.TestCase):
    @unittest.skipUnless(HAVE_DATA, "data files not found")
    def test_fixed_split_constants_match_the_data(self):
        sp = E.compute_split()
        print(f"\n    fixed split: {sp['n_is_days']} IS days + {sp['n_oos_days']} OOS days; SPLIT_DATE = {E.SPLIT_DATE} "
              f"(first OOS day), last IS day {sp['last_is_day']}", file=sys.stderr)
        self.assertEqual(sp["split_date"], E.SPLIT_DATE)
        self.assertEqual(sp["n_complete_days"], E.N_COMPLETE_DAYS)
        self.assertEqual(sp["n_is_days"], E.N_IS_DAYS)
        self.assertEqual(sp["n_oos_days"], E.N_OOS_DAYS)
        self.assertEqual((sp["first_day"], sp["last_day"]), (E.DATA_FIRST_DAY, E.DATA_LAST_DAY))
        # independent recount with zoneinfo-free arithmetic on the day table of the 5-minute bars
        b = E.load_bars(5)
        comp = b.days[b.days.n_rth_1m >= 370].date.to_numpy()
        self.assertEqual(len(comp), 3844)
        n_is = int(len(comp) * 0.6)
        self.assertEqual(n_is, 2306)
        self.assertEqual(str(comp[n_is])[:10], E.SPLIT_DATE)
        self.assertAlmostEqual(n_is / len(comp), 0.6, places=3)
        self.assertEqual(int(b.days.oos.sum()), int((b.days.date >= np.datetime64(E.SPLIT_DATE)).sum()))

    def test_a_trade_belongs_to_the_split_of_its_entry_day(self):
        times = ["2020-03-17 15:50", "2020-03-17 15:55", "2020-03-17 16:00", "2020-03-17 16:05", "2020-03-17 16:10",
                 "2020-03-17 18:00", "2020-03-17 18:05", "2020-03-18 10:00", "2020-03-18 10:05", "2020-03-18 10:10"]
        b = mk_at(times, flat(7000, 10))
        tr = trades(b, sig(10, long=[0, 5, 7]), max_bars=1)
        self.assertEqual(list(tr.entry_bar), [1, 6, 8])
        # 15:55 on 17 March is IS; 18:05 on 17 March already belongs to trading day 18 March = OOS
        self.assertEqual(list(tr.split), ["IS", "OOS", "OOS"])
        self.assertEqual(list(tr.entry_day.dt.strftime("%Y-%m-%d")), ["2020-03-17", "2020-03-18", "2020-03-18"])
        st = E.stats(tr)
        self.assertEqual((st["IS"]["trades"], st["OOS"]["trades"], st["ALL"]["trades"]), (1, 2, 3))
        self.assertEqual(st["split_date"], "2020-03-18")

    def test_stats_arithmetic(self):
        from datetime import date
        from scipy.special import betainc
        df = hand_trades()
        st = E.stats(df)
        s = st["IS"]
        self.assertEqual(s["trades"], 4)
        self.assertAlmostEqual(s["mean_net_pts"], 0.5)
        sd = math.sqrt((1.5 ** 2 + 1.5 ** 2 + 2.5 ** 2 + 2.5 ** 2) / 3)
        self.assertAlmostEqual(s["std_net_pts"], sd)
        t = 0.5 / (sd / 2)
        self.assertAlmostEqual(s["t_stat"], t)
        p = 0.5 * betainc(1.5, 0.5, 3 / (3 + t * t))            # one-sided Student t, 3 degrees of freedom
        self.assertAlmostEqual(s["p_one_sided"], p, places=10)
        self.assertAlmostEqual(s["win_rate"], 0.5)
        self.assertAlmostEqual(s["profit_factor"], 5.0 / 3.0)
        self.assertAlmostEqual(s["mean_r"], (1.0 - 0.5 - 0.5) / 3)
        self.assertEqual(s["trades_with_stop"], 3)
        self.assertAlmostEqual(s["mae_median_pts"], 2.0)        # 0.5, 1, 3, 4
        self.assertAlmostEqual(s["mae_p90_pts"], 3.7)           # linear interpolation: 3 + 0.7 * (4 - 3)
        self.assertAlmostEqual(s["median_minutes_held"], 12.5)
        self.assertEqual(s["net_pts_by_year"], {"2019": 4.0, "2020": -2.0})
        self.assertEqual(s["trades_by_year"], {"2019": 3, "2020": 1})
        self.assertAlmostEqual(s["total_net_pts"], 2.0)
        self.assertAlmostEqual(s["mean_gross_pts"], 1.25)
        is_years = (date(2020, 3, 18) - date(2010, 11, 15)).days / 365.25
        self.assertAlmostEqual(s["trades_per_year"], 4 / is_years)
        # day-clustered: daily sums 1.0 (two trades on 1 May), 3.0, -2.0
        self.assertEqual(s["days_traded"], 3)
        self.assertAlmostEqual(s["day_mean_net_pts"], 2.0 / 3)
        dsd = math.sqrt(((1 - 2 / 3) ** 2 + (3 - 2 / 3) ** 2 + (-2 - 2 / 3) ** 2) / 2)
        self.assertAlmostEqual(s["day_std_net_pts"], dsd)
        dt = (2.0 / 3) / (dsd / math.sqrt(3))
        self.assertAlmostEqual(s["day_t_stat"], dt)
        self.assertAlmostEqual(s["day_p_one_sided"], 0.5 * betainc(1.0, 0.5, 2 / (2 + dt * dt)), places=10)
        self.assertAlmostEqual(s["worst_day_net_pts"], -2.0)
        self.assertAlmostEqual(s["max_drawdown_pts"], 2.0)      # equity 2, 1, 4, 2: peak 4 -> 2
        o = st["OOS"]
        self.assertEqual(o["trades"], 4)
        self.assertAlmostEqual(o["mean_net_pts"], 1.5)
        self.assertAlmostEqual(o["win_rate"], 0.75)
        self.assertAlmostEqual(o["profit_factor"], 6.5 / 0.5)
        self.assertEqual(o["net_pts_by_year"], {"2020": 1.0, "2021": 1.0, "2022": 4.0})
        oos_years = (date(2026, 10, 31) - date(2020, 3, 18)).days / 365.25
        self.assertAlmostEqual(o["trades_per_year"], 4 / oos_years)
        self.assertEqual(o["days_traded"], 3)
        a = st["ALL"]
        self.assertEqual(a["trades"], 8)
        self.assertAlmostEqual(a["mean_net_pts"], 1.0)
        self.assertAlmostEqual(a["t_stat"], 1.0 / (np.std(df.net_pts, ddof=1) / math.sqrt(8)))
        self.assertAlmostEqual(a["p_one_sided"], float(sps.ttest_1samp(df.net_pts, 0.0, alternative="greater").pvalue))
        self.assertAlmostEqual(st["split_years"]["ALL"], is_years + oos_years)
        # a negative mean gives p > 0.5; no losing trade gives no profit factor
        st2 = E.stats(df.assign(net_pts=-df.net_pts))
        self.assertGreater(st2["ALL"]["p_one_sided"], 0.5)
        self.assertAlmostEqual(st2["ALL"]["p_one_sided"] + a["p_one_sided"], 1.0)
        st3 = E.stats(df.assign(net_pts=df.net_pts.abs()))
        self.assertIsNone(st3["ALL"]["profit_factor"])
        json.dumps(E._jsonable(st), allow_nan=False)

    def test_bootstrap_is_seeded_and_matches_a_plain_loop(self):
        rng = np.random.default_rng(7)
        x = rng.normal(0.4, 3.0, 300)
        ci = E.bootstrap_mean_ci(x)
        self.assertEqual(ci, E.bootstrap_mean_ci(x))            # the same every time
        self.assertNotEqual(ci, E.bootstrap_mean_ci(x, seed=1))
        # plain loop with the same generator: 2,000 resamples, percentile interval
        g = np.random.default_rng(E.BOOT_SEED)
        means = [x[g.integers(0, len(x), len(x))].mean() for _ in range(2000)]
        lo, hi = np.percentile(means, [2.5, 97.5])
        self.assertAlmostEqual(ci[0], lo, places=12)
        self.assertAlmostEqual(ci[1], hi, places=12)
        self.assertLess(ci[0], x.mean())
        self.assertGreater(ci[1], x.mean())
        se = x.std(ddof=1) / math.sqrt(len(x))
        self.assertAlmostEqual(ci[0], x.mean() - 1.96 * se, delta=0.25 * se)
        self.assertAlmostEqual(ci[1], x.mean() + 1.96 * se, delta=0.25 * se)
        self.assertEqual((E.BOOT_RESAMPLES, E.stats(hand_trades())["bootstrap"]["resamples"]), (2000, 2000))
        # the chunked version used for many trades gives the same numbers as the loop
        y = rng.normal(0.1, 2.0, 5000)                          # 5,000 trades -> 800 resamples per chunk
        g = np.random.default_rng(E.BOOT_SEED)
        means = [y[g.integers(0, len(y), len(y))].mean() for _ in range(2000)]
        lo, hi = np.percentile(means, [2.5, 97.5])
        ci = E.bootstrap_mean_ci(y)
        self.assertAlmostEqual(ci[0], lo, places=12)
        self.assertAlmostEqual(ci[1], hi, places=12)

    def test_stats_of_no_trades(self):
        b = mk(D0, flat(100, 4))
        st = E.stats(trades(b, sig(4)))
        self.assertEqual(st["ALL"]["trades"], 0)
        self.assertIsNone(st["ALL"]["mean_net_pts"])
        self.assertIsNone(st["OOS"]["t_stat"])
        json.dumps(E._jsonable(st), allow_nan=False)


# ---------------------------------------------------------------------------------------------------------------------
# 10. the runner
# ---------------------------------------------------------------------------------------------------------------------
def tiny_strategy(bars, params):
    d = np.zeros(bars.n, dtype=int)
    d[::params["every"]] = 1
    return E.Signals(d, stop_pts=params["stop_pts"], target_r=2.0, max_bars=3)


class TestRunner(unittest.TestCase):
    def setUp(self):
        self.m1 = synth_1m(["2024-01-09", "2024-01-10", "2024-01-11"], seed=9)
        self.bars = bars_from_1m(self.m1, 5)

    def test_writes_json_and_csv_and_never_overwrites_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "deep", "out")              # the folders do not exist yet
            params = {"every": 7, "stop_pts": 6.0}
            res = E.run_config("fam_A-001.v1", "demo family", params, tiny_strategy, 5, out_dir=out, bars=self.bars,
                               verbose=False)
            jp = os.path.join(out, "results", "fam_A-001.v1.json")
            cp = os.path.join(out, "trades", "fam_A-001.v1.csv")
            self.assertTrue(os.path.isfile(jp) and os.path.isfile(cp))
            with open(jp) as f:
                js = json.load(f)
            self.assertEqual(js, json.loads(json.dumps(res)))
            self.assertEqual(js["config_id"], "fam_A-001.v1")
            self.assertEqual(js["family"], "demo family")
            self.assertEqual(js["params"], params)
            self.assertEqual(js["engine_version"], E.ENGINE_VERSION)
            self.assertEqual(js["engine_sha256"], E.ENGINE_SHA256)
            self.assertEqual(js["data_file"], "synthetic")
            self.assertEqual(js["resolution_min"], 5)
            self.assertEqual(js["split_date"], E.SPLIT_DATE)
            self.assertEqual(js["path"], "arrays")
            self.assertTrue(js["tradeify_usable"])
            self.assertEqual(js["lookahead_check"], "passed")
            self.assertEqual(js["costs"], {"tick": 0.25, "stop_order_slippage_pts": 0.25, "round_trip_cost_pts": 0.75})
            for k in ("IS", "OOS", "ALL"):
                self.assertIn("mean_net_pts", js["stats"][k])
            csv = pd.read_csv(cp)
            self.assertEqual(list(csv.columns), E.TRADE_COLUMNS)
            self.assertEqual(len(csv), js["n_trades"])
            self.assertGreater(len(csv), 10)
            self.assertEqual(js["stats"]["ALL"]["trades"], len(csv))
            self.assertAlmostEqual(js["stats"]["ALL"]["total_net_pts"], csv.net_pts.sum(), places=4)
            self.assertTrue(str(csv.entry_time.iloc[0]).endswith("-05:00"))          # ET with its UTC offset
            before = (read(jp), read(cp))
            # a second run with the same id must refuse ...
            with self.assertRaises(FileExistsError):
                E.run_config("fam_A-001.v1", "demo family", {"every": 5, "stop_pts": 3.0}, tiny_strategy, 5, out_dir=out,
                             bars=self.bars, verbose=False)
            self.assertEqual(before, (read(jp), read(cp)))
            # ... also when only one of the two files is there
            os.unlink(jp)
            with self.assertRaises(FileExistsError):
                E.run_config("fam_A-001.v1", "demo family", params, tiny_strategy, 5, out_dir=out, bars=self.bars,
                             verbose=False)
            self.assertFalse(os.path.exists(jp))
            # ... unless told to
            res2 = E.run_config("fam_A-001.v1", "demo family", {"every": 5, "stop_pts": 3.0}, tiny_strategy, 5,
                                out_dir=out, bars=self.bars, overwrite=True, check_lookahead=False, verbose=False)
            self.assertEqual(json.loads(read(jp))["params"], {"every": 5, "stop_pts": 3.0})
            self.assertEqual(res2["lookahead_check"], "skipped")
            self.assertEqual(len(pd.read_csv(cp)), res2["n_trades"])
            self.assertEqual(sorted(os.listdir(os.path.join(out, "results"))), ["fam_A-001.v1.json"])   # no temp files
            self.assertEqual(sorted(os.listdir(os.path.join(out, "trades"))), ["fam_A-001.v1.csv"])

    def test_bad_ids_and_resolution_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            for bad in ("../x", "a/b", "", "a b", ".hidden"):
                with self.assertRaises(ValueError):
                    E.run_config(bad, "f", {"every": 7, "stop_pts": 6.0}, tiny_strategy, 5, out_dir=tmp, bars=self.bars)
            with self.assertRaises(ValueError):
                E.run_config("ok", "f", {"every": 7, "stop_pts": 6.0}, tiny_strategy, 15, out_dir=tmp, bars=self.bars)
            self.assertEqual(os.listdir(os.path.join(tmp, "results")), [])

    def test_callback_strategy_and_multi_day_flag_through_the_runner(self):
        def strat(bars, params):
            def on_bar(ctx):
                if ctx.position == 0 and ctx.i % 9 == 0:
                    ctx.buy_market(stop_pts=5.0, max_bars=4)
            return E.Callback(on_bar, allow_multi_day=True, last_entry=None)
        with tempfile.TemporaryDirectory() as tmp:
            res = E.run_config("cb1", "f", {}, strat, 5, out_dir=tmp, bars=self.bars, verbose=False)
            self.assertEqual(res["path"], "callback")
            self.assertFalse(res["tradeify_usable"])
            self.assertTrue(res["session"]["allow_multi_day"])
            self.assertGreater(res["n_trades"], 5)

    def test_runner_refuses_a_strategy_that_looks_ahead(self):
        def cheat(bars, params):
            nxt = np.r_[bars.c[1:], bars.c[-1]]
            return E.Signals(np.where(nxt > bars.c, 1, -1), max_bars=1)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(E.LookaheadError):
                E.run_config("cheat", "f", {}, cheat, 5, out_dir=tmp, bars=self.bars, verbose=False)
            self.assertEqual(os.listdir(os.path.join(tmp, "results")), [])
            self.assertEqual(os.listdir(os.path.join(tmp, "trades")), [])

    def test_default_output_folder(self):
        want = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "out")
        self.assertEqual(os.path.realpath(E.OUT_DIR), want)
        self.assertTrue(want.endswith(os.path.join("research3", "out")))


# ---------------------------------------------------------------------------------------------------------------------
# 11. real data: both paths agree, no lookahead, invariants, run time
# ---------------------------------------------------------------------------------------------------------------------
def strat_arrays(bars, p):
    """A two-sided strategy through path (a) that uses many helpers."""
    a = E.atr(bars.h, bars.l, bars.c, 14)
    orh, orl = E.opening_range(bars, "09:30", 30)
    dh, dl = E.donchian(bars.h, bars.l, 12, include_current=False)
    pr = E.prior_rth(bars)
    tw = E.twap_vwap_proxy(bars, "09:30")
    f = E.ema(bars.c, 20)
    da = E.daily_atr(bars, 14)
    win = bars.time_between("10:00", "14:30") & (da > 0)
    up = win & (bars.c > tw) & (f > E.lag(f, 3)) & (bars.c > pr["close"])
    dn = win & (bars.c < tw) & (f < E.lag(f, 3)) & (E.rsi(bars.c, 14) > 60)
    return E.Signals(long=dict(entry=up, order="stop", price=np.maximum(orh, dh) + 0.25, stop_pts=1.5 * a),
                     short=dict(entry=dn, order="limit", price=bars.c + 0.5 * a, stop_pts=1.5 * a),
                     target_r=2.0, expiry_bars=3, be_trigger_r=1.0, exit_time="15:30", max_trades_per_day=3)


def strat_callback(bars, p):
    """Path (b): a pullback entry with a hand-rolled trailing stop."""
    a = E.atr(bars.h, bars.l, bars.c, 14)
    f, s = E.ema(bars.c, 10), E.ema(bars.c, 40)
    c, lo = bars.c, bars.l
    rth = bars.rth

    def on_bar(ctx):
        i = ctx.i
        if ctx.position == 0:
            if rth[i] and f[i] > s[i] and c[i] < f[i] and not ctx.pending_long:
                ctx.buy_stop(bars.h[i] + 0.25, stop=lo[i] - a[i], expiry_bars=2)
        elif ctx.bars_held >= 3 and ctx.mfe > a[i]:
            new = c[i] - 1.5 * a[i]
            if ctx.stop is None or new > ctx.stop:
                ctx.set_stop(new)
    return E.Callback(on_bar, active=rth, exit_time="15:45")


def pair_arrays(bars, p):
    a = E.atr(bars.h, bars.l, bars.c, 14)
    m = E.sma(bars.c, 20)
    go = E.cross_above(bars.c, m) & bars.rth
    gs = E.cross_below(bars.c, m) & bars.rth
    if p["kind"] == "market":
        return E.Signals(np.where(go, 1, np.where(gs, -1, 0)), stop_pts=2 * a, target_r=1.5, exit_time="15:30",
                         max_trades_per_day=4, trail_r=1.0, trail_trigger_r=1.0)
    return E.Signals(long=dict(entry=go, order="stop", price=bars.h + 1.0, stop=bars.l - 1.0),
                     short=dict(entry=gs, order="limit", price=bars.c + 0.5 * a, stop_pts=3 * a),
                     target_pts=20.0, expiry_bars=3, max_bars=30, tp1_pts=8.0, tp1_frac=0.5, be_trigger_pts=6.0)


def pair_callback(bars, p):
    """The same rules as pair_arrays, written bar by bar."""
    a = E.atr(bars.h, bars.l, bars.c, 14)
    m = E.sma(bars.c, 20)
    go = E.cross_above(bars.c, m) & bars.rth
    gs = E.cross_below(bars.c, m) & bars.rth
    h, l, c = bars.h, bars.l, bars.c
    if p["kind"] == "market":
        def on_bar(ctx):
            i = ctx.i
            if ctx.position == 0:
                if go[i]:
                    ctx.buy_market(stop_pts=2 * a[i], target_r=1.5)
                elif gs[i]:
                    ctx.sell_market(stop_pts=2 * a[i], target_r=1.5)
        return E.Callback(on_bar, exit_time="15:30", max_trades_per_day=4, trail_r=1.0, trail_trigger_r=1.0)

    def on_bar(ctx):
        i = ctx.i
        if ctx.position == 0:
            if go[i]:
                ctx.buy_stop(h[i] + 1.0, stop=l[i] - 1.0, target_pts=20.0, expiry_bars=3, tp1_pts=8.0)
            if gs[i]:
                ctx.sell_limit(c[i] + 0.5 * a[i], stop_pts=3 * a[i], target_pts=20.0, expiry_bars=3, tp1_pts=8.0)
    return E.Callback(on_bar, max_bars=30, tp1_frac=0.5, be_trigger_pts=6.0)


def ref_backtest(b, direction, kind, price, stop, target, expiry, max_bars):
    """An independent, slow, deliberately plain re-statement of the rules for one-directional strategies (default
    intraday session rules).  Returns a list of (entry_bar, exit_bar, entry_price, exit_price, reason, net)."""
    o, h, l, c = b.o, b.h, b.l, b.c
    n = b.n
    start_min = (b.mod.astype(int) - 18 * 60) % 1440             # minutes since 18:00 at the bar open
    end_min = start_min + b.res                                  # ... at the bar end (5-minute bars: never cut)
    day = b.tday_id
    LAST_ENTRY, FLAT = (15 * 60 + 55 - 18 * 60) % 1440, (16 * 60 + 10 - 18 * 60) % 1440

    def may_hold(j):
        return end_min[j] <= FLAT

    def is_flat_bar(j):
        return may_hold(j) and not (j + 1 < n and day[j + 1] == day[j] and may_hold(j + 1))

    out = []
    pos = None
    order = None
    for j in range(n):
        if pos is None and order is not None:                    # 1. a waiting entry order
            if j > order["last"] or day[j] != order["day"]:
                order = None
            else:
                side, p = order["side"], order["price"]
                usable = (not b.incomplete[j]) and may_hold(j)
                raw = None
                if order["kind"] == "market":
                    if usable and start_min[j] <= LAST_ENTRY:
                        raw = o[j]
                elif usable and end_min[j] <= LAST_ENTRY:
                    if order["kind"] == "stop":
                        if side > 0 and h[j] >= p:
                            raw = max(p, o[j])
                        if side < 0 and l[j] <= p:
                            raw = min(p, o[j])
                    else:
                        if side > 0 and l[j] < p:
                            raw = min(p, o[j])
                        if side < 0 and h[j] > p:
                            raw = max(p, o[j])
                if raw is not None:
                    entry = raw + 0.25 * side if order["kind"] == "stop" else raw
                    pos = dict(order, entry=entry, raw=raw, bar=j)
                    order = None
                elif order["kind"] == "market":
                    order = None
        if pos is not None:                                      # 2. the open position in bar j
            side = pos["side"]
            first = pos["bar"] == j
            ref = pos["raw"] if first else o[j]
            adverse, favour = (l[j], h[j]) if side > 0 else (h[j], l[j])
            done = None
            if (adverse - pos["stop"]) * side <= 0:
                raw = min(pos["stop"], ref) if side > 0 else max(pos["stop"], ref)
                done = (raw - 0.25 * side, "stop")
            elif (favour - pos["target"]) * side > 0 and not (first and pos["kind"] != "market"):
                done = (pos["target"], "target")
            elif j - pos["bar"] + 1 >= max_bars:
                done = (c[j], "bars")
            elif is_flat_bar(j):
                done = (c[j], "eod")
            if done is not None:
                net = (done[0] - pos["entry"]) * side - 0.75
                out.append((pos["bar"], j, pos["entry"], done[0], done[1], net))
                pos = None
        if pos is None and direction[j] != 0 and j + 1 < n:      # 3. a new signal at the close of bar j
            vals = (price[j], stop[j], target[j])
            carried = day[j + 1] != day[j] and end_min[j] < 22 * 60 + 15     # day ends early: nothing is carried
            if not any(v != v for v in vals) and not carried:
                order = dict(side=int(direction[j]), kind=kind, price=price[j], stop=stop[j], target=target[j],
                             last=j + 1 if kind == "market" else j + expiry, day=day[j + 1])
    return out


@unittest.skipUnless(HAVE_DATA, "data files not found")
class TestRealData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = E.load_bars(5)

    def test_engine_matches_an_independent_plain_simulator(self):
        b = self.b.truncate(70_000)
        a = E.atr(b.h, b.l, b.c, 14)
        m = E.sma(b.c, 30)
        total = 0
        for side in (1, -1):
            go = ((b.c - m) * side > 0) & ((b.c - b.o) * side < 0)          # a pullback bar on the trend side
            d = np.where(go, side, 0)
            for kind, price in (("market", b.c), ("stop", b.c + side * 0.4 * a), ("limit", b.c - side * 0.3 * a)):
                stop = b.c - side * 1.2 * a
                target = b.c + side * 1.8 * a
                got = E.run(b, E.Signals(d, order=kind, price=price, stop=stop, target=target, expiry_bars=4,
                                         max_bars=25)).trades
                want = ref_backtest(b, d, kind, price, stop, target, 4, 25)
                self.assertEqual(len(got), len(want), (side, kind))
                self.assertGreater(len(got), 800, (side, kind))
                w = pd.DataFrame(want, columns=["entry_bar", "exit_bar", "entry_price", "exit_price", "exit_reason", "net"])
                self.assertTrue(np.array_equal(got.entry_bar.to_numpy(), w.entry_bar.to_numpy()), (side, kind))
                self.assertTrue(np.array_equal(got.exit_bar.to_numpy(), w.exit_bar.to_numpy()), (side, kind))
                self.assertTrue(np.allclose(got.entry_price, w.entry_price, atol=1e-9), (side, kind))
                self.assertTrue(np.allclose(got.exit_price, w.exit_price, atol=1e-9), (side, kind))
                self.assertEqual(list(got.exit_reason), list(w.exit_reason), (side, kind))
                self.assertTrue(np.allclose(got.net_pts, w.net, atol=1e-9), (side, kind))
                self.assertGreaterEqual(len(set(got.exit_reason)), 3, (side, kind))
                total += len(got)
        self.assertGreater(total, 8000)

    def test_incomplete_flags_of_real_bars_come_from_the_1_minute_file(self):
        b1 = E.load_bars(1)
        b5 = self.b
        per_day = np.bincount(b1.day_idx[b1.rth], minlength=len(b1.days))
        self.assertTrue(np.array_equal(per_day, b1.days.n_rth_1m.to_numpy()))
        self.assertTrue(np.array_equal(b1.days.complete.to_numpy(), per_day >= 370))
        self.assertEqual(int((per_day >= 370).sum()), E.N_COMPLETE_DAYS)
        self.assertTrue(np.array_equal(b1.days.tday_id.to_numpy(), b5.days.tday_id.to_numpy()))
        self.assertTrue(np.array_equal(b1.days.complete.to_numpy(), b5.days.complete.to_numpy()))
        self.assertTrue(np.array_equal(b1.days.n_rth_1m.to_numpy(), b5.days.n_rth_1m.to_numpy()))
        # session levels agree between the 1-minute and the 5-minute bars
        for k in ("rth_open", "rth_high", "rth_low", "rth_close"):
            self.assertTrue(np.array_equal(b1.days[k].to_numpy(), b5.days[k].to_numpy(), equal_nan=True), k)
        self.assertFalse(((b1.mod >= 975) & (b1.mod < 1080)).any())

    def test_both_paths_give_identical_trades(self):
        sub = self.b.truncate(260_000)
        for kind in ("market", "resting"):
            ra = E.run(sub, pair_arrays(sub, {"kind": kind}))
            rb = E.run(sub, pair_callback(sub, {"kind": kind}))
            self.assertGreater(len(ra.trades), 1500, kind)
            pd.testing.assert_frame_equal(ra.trades, rb.trades)
            self.assertEqual((ra.path, rb.path), ("arrays", "callback"))
            self.assertGreater(len(set(ra.trades.exit_reason)), 2)

    def test_no_lookahead_property_on_the_full_data(self):
        b = self.b
        for fn in (strat_arrays, strat_callback):
            full = E.run(b, fn(b, {})).trades
            self.assertGreater(len(full), 1000)
            for k in (523_456, b.n - 100_003):
                tb = b.truncate(k)
                part = E.run(tb, fn(tb, {})).trades
                a = full[full.exit_bar < k - 1].reset_index(drop=True)
                p = part[part.exit_bar < k - 1].reset_index(drop=True)
                self.assertGreater(len(a), 100)
                self.assertGreaterEqual(len(part), len(p))
                pd.testing.assert_frame_equal(a, p)             # every trade that closed before k is identical
            self.assertEqual(E.check_no_lookahead(fn, {}, b, cuts=[400_001]), [])
            self.assertEqual(E.check_no_lookahead(fn, {}, b), [])               # the quick default version

    def test_lookahead_is_detected(self):
        b = self.b.truncate(60_000)

        def peek_one_bar(bars, p):                                # tomorrow's newspaper, one bar
            nxt = np.r_[bars.c[1:], bars.c[-1]]
            return E.Signals(np.where(nxt > bars.c, 1, -1), max_bars=1)

        def peek_day_high(bars, p):                               # the day's final high, known only at the close
            day_high = bars.days.rth_high.to_numpy()[bars.day_idx]
            return E.Signals(bars.rth.astype(int), order="limit", price=day_high - 50.0, max_bars=5)

        def peek_global(bars, p):                                 # a whole-sample statistic
            z = (bars.c - bars.c.mean()) / bars.c.std()
            return E.Signals(np.where(z < -1, 1, 0), max_bars=10)

        def peek_callback(bars, p):                               # a callback that reads bar i + 5
            c = bars.c
            def on_bar(ctx):
                j = min(ctx.i + 5, bars.n - 1)
                if ctx.position == 0 and c[j] > c[ctx.i] + 2:
                    ctx.buy_market(max_bars=2)
            return E.Callback(on_bar)

        def peek_callback_index(bars, p):                         # a callback that reads bar i + 1 without care
            c = bars.c
            def on_bar(ctx):
                if ctx.position == 0 and c[ctx.i + 1] > c[ctx.i]:
                    ctx.buy_market(max_bars=2)
            return E.Callback(on_bar)

        for fn in (peek_one_bar, peek_day_high, peek_global, peek_callback, peek_callback_index):
            problems = E.check_no_lookahead(fn, {}, b)
            self.assertTrue(problems, fn.__name__)
        self.assertEqual(E.check_no_lookahead(strat_arrays, {}, b), [])

    def test_real_regular_session_is_0930_to_1600_new_york_time_in_every_dst_week(self):
        from datetime import date
        b = self.b
        d = b.days
        by_date = {str(x)[:10]: k for k, x in enumerate(d.date.to_numpy())}
        utc = ZoneInfo("UTC")
        checked = 0
        for year in range(2011, 2027):
            mar = date(year, 3, 8)
            mar += timedelta(days=(6 - mar.weekday()) % 7)        # second Sunday of March: clocks go forward
            nov = date(year, 11, 1)
            nov += timedelta(days=(6 - nov.weekday()) % 7)        # first Sunday of November: clocks go back
            for change, before, after in ((mar, (14, 30), (13, 30)), (nov, (13, 30), (14, 30))):
                for day, want in ((change - timedelta(days=2), before), (change + timedelta(days=1), after)):
                    k = by_date.get(day.isoformat())
                    if k is None or d.rth_first.iloc[k] < 0 or d.rth_first_mod.iloc[k] != 570:
                        continue
                    i0, i1 = int(d.rth_first.iloc[k]), int(d.rth_last.iloc[k])
                    u = datetime.fromtimestamp(int(b.t[i0]), utc)
                    self.assertEqual((u.hour, u.minute), want, day)        # 09:30 ET in UTC, winter / summer clock
                    lt0, lt1 = local(b.t[i0]), local(b.t[i1])
                    self.assertEqual((lt0.hour, lt0.minute), (9, 30), day)
                    self.assertLessEqual((lt1.hour, lt1.minute), (15, 55), day)
                    self.assertEqual(lt0.date(), day)
                    checked += 1
        self.assertGreater(checked, 50)
        # every regular-session bar of a random sample, and the first / last one of every day, by zoneinfo
        rng = np.random.default_rng(1)
        idx = np.r_[rng.choice(np.flatnonzero(b.rth), 3000), d.rth_first[d.rth_first >= 0].to_numpy(),
                    d.rth_last[d.rth_last >= 0].to_numpy()]
        for i in idx:
            lt = local(b.t[i])
            self.assertTrue(570 <= lt.hour * 60 + lt.minute <= 955, lt)
        for i in rng.choice(np.flatnonzero(~b.rth), 3000):
            lt = local(b.t[i])
            m = lt.hour * 60 + lt.minute
            self.assertTrue(m < 570 or m >= 960, lt)
            self.assertFalse(975 <= m < 1080, lt)

    def test_session_invariants_on_a_dense_run(self):
        b = self.b
        d = np.where(E.cross_above(E.sma(b.c, 10), E.sma(b.c, 30)), 1, np.where(E.cross_below(E.sma(b.c, 10), E.sma(b.c, 30)), -1, 0))
        r = E.run(b, E.Signals(d, stop_pts=E.atr(b.h, b.l, b.c, 14) * 2, target_r=2.0))
        tr = r.trades
        self.assertGreater(len(tr), 20_000)
        e, x = tr.entry_bar.to_numpy(), tr.exit_bar.to_numpy()
        self.assertFalse(b.incomplete[e].any())                              # no entry on an incomplete day
        self.assertTrue((b.tmin[e] <= E.tmin_of("15:55")).all())             # no entry after 15:55 ET
        self.assertTrue((b.tday_id[e] == b.tday_id[x]).all())                # never across the end of the trading day
        self.assertTrue((b.tmin_end[x] <= E.TMIN_FLAT).all())                # flat by 16:10 ET
        self.assertTrue((e[1:] >= x[:-1]).all())                             # one position at a time
        self.assertTrue((e == tr.signal_bar.to_numpy() + 1).all())           # market orders: the next bar
        self.assertTrue(np.array_equal(tr.entry_price.to_numpy(), b.o[e]))   # ... at its open
        self.assertTrue(np.allclose(tr.net_pts, tr.gross_pts - 0.75))
        self.assertTrue(np.allclose(tr.gross_pts, tr.direction * (tr.exit_price - tr.entry_price)))
        self.assertEqual(set(tr.exit_reason), {"stop", "target", "eod"})
        self.assertEqual(set(tr.slippage_pts[tr.exit_reason == "stop"]), {0.25})
        self.assertEqual(set(tr.slippage_pts[tr.exit_reason != "stop"]), {0.0})
        eod = tr[tr.exit_reason == "eod"]
        self.assertTrue(np.array_equal(eod.exit_price.to_numpy(), b.c[eod.exit_bar.to_numpy()]))
        self.assertTrue((eod.exit_time.dt.hour * 60 + eod.exit_time.dt.minute <= 16 * 60 + 10).all())
        st_ = tr[tr.exit_reason == "stop"]
        raw = st_.exit_price + 0.25 * st_.direction                          # undo the tick of slippage
        xb = st_.exit_bar.to_numpy()
        gap = np.where(st_.direction > 0, b.o[xb] < st_.stop_price, b.o[xb] > st_.stop_price) & (xb > st_.entry_bar.to_numpy())
        self.assertTrue(np.allclose(raw[~gap], st_.stop_price[~gap]))         # at the stop price ...
        self.assertTrue(np.allclose(raw[gap], b.o[xb][gap]))                  # ... or the open after a gap through it
        self.assertGreater(int(gap.sum()), 10)
        tg = tr[tr.exit_reason == "target"]
        self.assertTrue(np.allclose(tg.exit_price, tg.target_price))
        self.assertTrue((np.where(tg.direction > 0, b.h[tg.exit_bar.to_numpy()] > tg.target_price,
                                  b.l[tg.exit_bar.to_numpy()] < tg.target_price)).all())
        self.assertTrue((tr.mae_pts >= 0).all() and (tr.mfe_pts >= 0).all())
        self.assertTrue(r.tradeify_usable)
        # every split has trades and the year table adds up
        st = E.stats(tr)
        self.assertEqual(st["IS"]["trades"] + st["OOS"]["trades"], st["ALL"]["trades"])
        self.assertAlmostEqual(sum(st["ALL"]["net_pts_by_year"].values()), tr.net_pts.sum(), places=6)
        self.assertEqual(sorted(st["ALL"]["net_pts_by_year"])[0], "2010")
        self.assertTrue((tr.split[tr.entry_day < E.SPLIT_DATE] == "IS").all())
        self.assertTrue((tr.split[tr.entry_day >= E.SPLIT_DATE] == "OOS").all())

    def test_session_invariants_at_other_resolutions(self):
        for res, last_open, flat_end in ((15, "15:45", "16:00"), (1, "15:55", "16:10"), (30, "15:30", "16:00")):
            b = E.load_bars(res)
            self.assertFalse(((b.mod >= 975) & (b.mod < 1080)).any())
            f, s = E.sma(b.c, 8), E.sma(b.c, 21)
            d = np.where(E.cross_above(f, s), 1, np.where(E.cross_below(f, s), -1, 0))
            a = E.atr(b.h, b.l, b.c, 14)
            for strat in (E.Signals(d, stop_pts=2 * a, target_r=1.5),
                          E.Signals(d, order="stop", price=b.c + d * 0.5 * a, stop_pts=2 * a, expiry_bars=3)):
                tr = E.run(b, strat).trades
                self.assertGreater(len(tr), 3000, res)
                e, x = tr.entry_bar.to_numpy(), tr.exit_bar.to_numpy()
                self.assertFalse(b.incomplete[e].any(), res)
                self.assertTrue((b.tday_id[e] == b.tday_id[x]).all(), res)
                self.assertTrue((b.tmin_end[x] <= E.TMIN_FLAT).all(), res)
                self.assertTrue((b.tmin[e] <= E.tmin_of("15:55")).all(), res)
                self.assertEqual(b.tmin[e].max(), E.tmin_of(last_open) if strat.sides[1]["order"] == "market"
                                 else b.tmin[e].max(), res)
                eod = tr[tr.exit_reason == "eod"]
                self.assertGreater(len(eod), 100, res)
                last = eod.exit_time.dt.strftime("%H:%M")
                self.assertEqual(last.max(), flat_end, res)
                if strat.sides[1]["order"] == "stop":            # a stop entry needs a bar that ENDS by 15:55
                    self.assertTrue((b.tmin_end[e] <= E.tmin_of("15:55")).all(), res)
                    raw = tr.entry_price - 0.25 * tr.direction
                    self.assertTrue((np.where(tr.direction > 0, b.h[e] >= raw - 1e-9, b.l[e] <= raw + 1e-9)).all(), res)

    def test_run_time_16_years_of_5_minute_bars(self):
        b = self.b
        years = (b.t[-1] - b.t[0]) / (365.25 * 86400)
        self.assertGreater(years, 15.9)
        out = []
        for name, fn in (("opening-range breakout", E._demo_orb), ("SMA cross, always in the market", E._demo_sma)):
            t0 = time.perf_counter()
            res = E.run(b, fn(b, {}))
            E.stats(res.trades)
            dt = time.perf_counter() - t0
            out.append(f"{name}: {dt:.2f}s for {len(res.trades)} trades")
            self.assertLess(dt, 20.0)
            self.assertGreater(len(res.trades), 3000)
        print(f"\n    path (a) on {b.n} five-minute bars ({years:.1f} years), signals + simulation + stats: "
              + "; ".join(out), file=sys.stderr)


# ---------------------------------------------------------------------------------------------------------------------
# 12. the worked examples of ENGINE.md run as written
# ---------------------------------------------------------------------------------------------------------------------
@unittest.skipUnless(HAVE_DATA, "data files not found")
class TestDocExamples(unittest.TestCase):
    def test_engine_md_examples(self):
        import re
        here = os.path.dirname(os.path.abspath(__file__))
        text = read(os.path.join(here, "ENGINE.md"))
        blocks = re.findall(r"<!-- example: (path-[ab]) -->\n```python\n(.*?)```", text, flags=re.S)
        self.assertEqual([b[0] for b in blocks], ["path-a", "path-b"])
        old = E.OUT_DIR
        with tempfile.TemporaryDirectory() as tmp:
            E.OUT_DIR = tmp                       # the examples write to the default folder: point it at a temp one
            try:
                for name, code in blocks:
                    ns = {"__file__": os.path.join(here, "example.py"), "__name__": "example"}
                    with open(os.devnull, "w") as devnull:
                        stdout, sys.stdout = sys.stdout, devnull
                        try:
                            exec(compile(code, f"ENGINE.md:{name}", "exec"), ns)
                        finally:
                            sys.stdout = stdout
                    res = ns["res"]
                    self.assertEqual(res["path"], "arrays" if name == "path-a" else "callback")
                    self.assertEqual(res["lookahead_check"], "passed")
                    self.assertTrue(res["tradeify_usable"])
                    self.assertGreater(res["stats"]["IS"]["trades"], 300, name)
                    self.assertGreater(res["stats"]["OOS"]["trades"], 200, name)
                    self.assertTrue(os.path.isfile(os.path.join(tmp, "results", res["config_id"] + ".json")))
                    self.assertTrue(os.path.isfile(os.path.join(tmp, "trades", res["config_id"] + ".csv")))
            finally:
                E.OUT_DIR = old


if __name__ == "__main__":
    unittest.main(verbosity=1)
