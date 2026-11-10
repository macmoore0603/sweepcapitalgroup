#!/usr/bin/env python3
"""engine.py - the ONE shared backtest engine for the research3 strategy tests.

Every strategy test uses this file unchanged, so that fills, costs, session rules and statistics are identical.
FAMILY MODULES MUST NOT CHANGE THIS FILE (nor patch its constants or functions at run time): import it and use it.
Read ENGINE.md (same folder) for the API, two worked examples, and the rules.  Run with:  python3 -I ...

Sections
  1. constants                         5. simulator (one bar-by-bar state machine for both strategy paths)
  2. time helpers, Bars, loading       6. trades table and statistics (fixed IS/OOS split)
  3. resampling                        7. runner (run_config), no-lookahead check, self-check (__main__)
  4. indicator helpers
"""
from __future__ import annotations

import array
import bisect
import hashlib
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd
from scipy import stats as _sps
from scipy.signal import lfilter as _lfilter

# =====================================================================================================================
# 1. CONSTANTS (never change these from a strategy module)
# =====================================================================================================================
ENGINE_VERSION = "research3-engine-1.0.1"

_HERE = os.path.dirname(os.path.realpath(__file__))
BASE_DIR = os.path.dirname(_HERE)                       # .../research3
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_DIR = os.path.join(BASE_DIR, "out")
FILE_1M = os.path.join(DATA_DIR, "NSX_1m.npz")
FILE_5M = os.path.join(DATA_DIR, "NSX_5m.npz")
NY = "America/New_York"

TICK = 0.25                 # index points
SLIPPAGE = 1 * TICK         # paid by every fill of a STOP order (stop entry, protective stop exit)
COST_RT = 0.75              # index points per trade, round trip, on top of slippage

# Clock (minute of day, New York time)
MOD_RTH_OPEN = 9 * 60 + 30      # 09:30
MOD_RTH_CLOSE = 16 * 60         # 16:00
MOD_FLAT = 16 * 60 + 10         # 16:10  intraday positions are flat by the close of the last bar that ends by this time
MOD_DAY_END = 16 * 60 + 15      # 16:15  end of the trading day; no bar that opens at or after this time is used
MOD_DAY_START = 18 * 60         # 18:00  start of the next trading day
# The same instants as "tmin" = minutes since the 18:00 start of the trading day (18:00 -> 0 ... 16:15 -> 1335)
TMIN_RTH_OPEN = (MOD_RTH_OPEN - MOD_DAY_START) % 1440     # 930
TMIN_RTH_CLOSE = (MOD_RTH_CLOSE - MOD_DAY_START) % 1440   # 1320
TMIN_FLAT = (MOD_FLAT - MOD_DAY_START) % 1440             # 1330
TMIN_DAY_END = (MOD_DAY_END - MOD_DAY_START) % 1440       # 1335

MIN_RTH_1M_BARS = 370       # a regular session with fewer 1-minute bars than this is "incomplete": no entries that day

# Fixed in-sample / out-of-sample split, identical for every test (see compute_split(); checked by the unit tests):
# the complete regular-session days in NSX_1m.npz are put in order; the first 60% are IS, the last 40% are OOS.
IS_FRACTION = 0.60
SPLIT_DATE = "2020-03-18"       # first OOS trading day; a trade is OOS when its entry trading day >= SPLIT_DATE
DATA_FIRST_DAY = "2010-11-15"   # first complete regular-session day
DATA_LAST_DAY = "2026-10-30"    # last complete regular-session day
N_COMPLETE_DAYS = 3844
N_IS_DAYS = 2306
N_OOS_DAYS = 1538

BOOT_SEED = 12345           # seed of the bootstrap of the mean (same for every test)
BOOT_RESAMPLES = 2000

MARKET, STOP, LIMIT = 0, 1, 2
_ORDER_CODES = {"market": MARKET, "stop": STOP, "limit": LIMIT}
_ORDER_NAMES = ("market", "stop", "limit")
_BIG = 1 << 60


def _file_sha256(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


ENGINE_SHA256 = _file_sha256(os.path.realpath(__file__))


# =====================================================================================================================
# 2. TIME HELPERS, BARS, LOADING
# =====================================================================================================================
def hm(x):
    """'HH:MM' (or an int minute of day) -> minute of day in New York time, e.g. hm('09:30') == 570."""
    if isinstance(x, (int, np.integer)) and not isinstance(x, bool):
        m = int(x)
    else:
        mt = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(x))
        if not mt:
            raise ValueError(f"time must look like 'HH:MM', got {x!r}")
        m = int(mt.group(1)) * 60 + int(mt.group(2))
    if not 0 <= m < 1440:
        raise ValueError(f"time out of range: {x!r}")
    return m


def tmin_of(x):
    """Clock time -> minutes since the 18:00 ET start of the trading day (18:00 -> 0, 00:00 -> 360, 09:30 -> 930,
    16:00 -> 1320, 16:10 -> 1330, 16:15 -> 1335).  All time-of-day rules compare in this unit so that the evening
    session sorts before the following morning."""
    return (hm(x) - MOD_DAY_START) % 1440


def local_seconds(t_utc):
    """Epoch seconds UTC -> 'local epoch' seconds (New York wall clock expressed as if it were UTC).  DST-safe:
    the conversion uses the tz database through pandas.  local // 86400 is the New York calendar day number and
    (local % 86400) // 60 the New York minute of day."""
    t = np.asarray(t_utc, dtype="int64")
    idx = pd.DatetimeIndex(t.astype("datetime64[s]"), tz="UTC")
    loc = idx.tz_convert(NY).tz_localize(None)
    return np.asarray(loc.values.astype("datetime64[s]").astype("int64"))


def _ro(a):
    a = np.ascontiguousarray(a)
    a.setflags(write=False)
    return a


# compact containers for the bar-by-bar loop (fast scalar access, little memory)
def _dbl(a):
    x = array.array("d")
    x.frombytes(np.ascontiguousarray(a, dtype="float64").tobytes())
    return x


def _i64(a):
    x = array.array("q")
    x.frombytes(np.ascontiguousarray(a, dtype="int64").tobytes())
    return x


def _flags(a):
    return np.ascontiguousarray(a, dtype=bool).astype("uint8").tobytes()


class Bars:
    """OHLC bars plus per-bar session fields (all numpy arrays of length n, read-only).

    t          bar OPEN time, epoch seconds UTC             t_end     nominal bar end, epoch seconds UTC
    o h l c    prices (index points)                        res       bar length in minutes
    date       New York calendar date (datetime64[D])       mod       New York minute of day at the bar open (0..1439)
    wd         weekday of `date` (Mon=0 .. Sun=6)           end_mod   New York minute of day at the nominal bar end
    tday       trading-day date (datetime64[D]); a trading day runs 18:00 ET (previous evening) -> 16:15 ET
    tday_id    the same as an integer (days since 1970-01-01)   tday_wd  weekday of the trading day (Mon=0)
    tmin       minutes since the 18:00 start of the trading day at the bar open; tmin_end at the nominal bar end
    rth        True when the bar lies inside the regular session 09:30-16:00 ET
    incomplete True when the bar's trading day has fewer than 370 regular-session 1-MINUTE bars (from NSX_1m.npz)
    day_idx    row of the bar's trading day in `days`
    days       DataFrame, one row per trading day: date, tday_id, first, last (bar index range), rth_first, rth_last,
               rth_open/high/low/close, rth_first_mod, n_rth_1m, complete, oos

    Only closed bars may be used by a strategy: a value computed for bar i may use bars <= i only.
    """

    def __init__(self, t, o, h, l, c, res, *, tmin_end=None, incomplete=None, rth_counts=None, source="synthetic"):
        t = np.asarray(t, dtype="int64")
        o, h, l, c = (np.asarray(x, dtype="float64") for x in (o, h, l, c))
        n = len(t)
        if not (len(o) == len(h) == len(l) == len(c) == n):
            raise ValueError("t, o, h, l, c must have the same length")
        if n == 0:
            raise ValueError("no bars")
        if n > 1 and (np.diff(t) <= 0).any():
            raise ValueError("bar times must be strictly increasing")
        if (h < l).any() or (h < np.maximum(o, c) - 1e-9).any() or (l > np.minimum(o, c) + 1e-9).any():
            raise ValueError("inconsistent OHLC (need low <= open, close <= high)")
        res = int(res)
        if res < 1:
            raise ValueError("res must be a positive number of minutes")
        loc = local_seconds(t)
        lday = loc // 86400
        mod = (loc % 86400) // 60
        if ((mod >= MOD_DAY_END) & (mod < MOD_DAY_START)).any():
            raise ValueError("bars that open between 16:15 and 18:00 ET are never used; drop them first")
        tmin = (mod - MOD_DAY_START) % 1440
        tday_id = lday + (mod >= MOD_DAY_START)
        if tmin_end is None:
            te = np.minimum(tmin + res, TMIN_DAY_END)
        else:
            te = np.asarray(tmin_end, dtype="int64")
            if len(te) != n or (te <= tmin).any() or (te > TMIN_DAY_END).any():
                raise ValueError("bad tmin_end")
        self.n = n
        self.res = res
        self.source = source
        self.t = _ro(t)
        self.o, self.h, self.l, self.c = _ro(o), _ro(h), _ro(l), _ro(c)
        self.t_end = _ro(t + (te - tmin) * 60)
        self.date = _ro(lday.astype("datetime64[D]"))
        self.mod = _ro(mod.astype("int16"))
        self.end_mod = _ro(((mod + (te - tmin)) % 1440).astype("int16"))
        self.wd = _ro(((lday + 3) % 7).astype("int8"))
        self.tday_id = _ro(tday_id.astype("int64"))
        self.tday = _ro(tday_id.astype("datetime64[D]"))
        self.tday_wd = _ro(((tday_id + 3) % 7).astype("int8"))
        self.tmin = _ro(tmin.astype("int16"))
        self.tmin_end = _ro(te.astype("int16"))
        rth = (tmin >= TMIN_RTH_OPEN) & (te <= TMIN_RTH_CLOSE)
        self.rth = _ro(rth)

        # ---- trading-day table ------------------------------------------------------------------------------------
        chg = np.flatnonzero(np.diff(tday_id) != 0) + 1
        first = np.r_[0, chg].astype("int64")
        last = np.r_[chg - 1, n - 1].astype("int64")
        nd = len(first)
        day_idx = np.zeros(n, dtype="int64")
        day_idx[chg] = 1
        day_idx = np.cumsum(day_idx)
        self.day_idx = _ro(day_idx.astype("int32"))
        rth_first = np.full(nd, -1, dtype="int64")
        rth_last = np.full(nd, -1, dtype="int64")
        ro = np.full(nd, np.nan); rh = np.full(nd, np.nan); rl = np.full(nd, np.nan); rc = np.full(nd, np.nan)
        ri = np.flatnonzero(rth)
        if len(ri):
            rd = day_idx[ri]
            rs = np.flatnonzero(np.r_[True, rd[1:] != rd[:-1]])
            re_ = np.r_[rs[1:] - 1, len(ri) - 1]
            dd = rd[rs]
            rth_first[dd] = ri[rs]
            rth_last[dd] = ri[re_]
            ro[dd] = o[ri[rs]]
            rc[dd] = c[ri[re_]]
            rh[dd] = np.maximum.reduceat(h[ri], rs)
            rl[dd] = np.minimum.reduceat(l[ri], rs)
        day_tid = tday_id[first]
        n1m = np.full(nd, -1, dtype="int64")
        if rth_counts is not None:
            ids, cnt = (np.asarray(x, dtype="int64") for x in rth_counts)
            n1m = np.zeros(nd, dtype="int64")
            if len(ids):
                pos = np.searchsorted(ids, day_tid)
                pos_c = np.minimum(pos, len(ids) - 1)
                hit = (pos < len(ids)) & (ids[pos_c] == day_tid)
                n1m = np.where(hit, cnt[pos_c], 0)
        if incomplete is not None:
            inc_bar = np.asarray(incomplete, dtype=bool)
            if len(inc_bar) != n:
                raise ValueError("incomplete must have one flag per bar")
            day_inc = np.logical_or.reduceat(inc_bar, first)
        elif rth_counts is not None:
            day_inc = n1m < MIN_RTH_1M_BARS
        else:
            day_inc = np.zeros(nd, dtype=bool)
        self.incomplete = _ro(day_inc[day_idx])
        split_id = int(np.datetime64(SPLIT_DATE, "D").astype("int64"))
        self.days = pd.DataFrame({
            "date": day_tid.astype("datetime64[D]"), "tday_id": day_tid, "first": first, "last": last,
            "rth_first": rth_first, "rth_last": rth_last, "rth_open": ro, "rth_high": rh, "rth_low": rl, "rth_close": rc,
            "rth_first_mod": np.where(rth_first >= 0, mod[np.maximum(rth_first, 0)], -1),
            "n_rth_1m": n1m, "complete": ~day_inc, "oos": day_tid >= split_id,
        })
        self._rth_counts = rth_counts
        self._lists_cache = None
        self._flag_cache = {}
        self._et = None

    # -- convenience ------------------------------------------------------------------------------------------------
    @property
    def et(self):
        """Bar open times as a tz-aware pandas DatetimeIndex in New York time (built on first use)."""
        if self._et is None:
            self._et = pd.DatetimeIndex(self.t.astype("datetime64[s]"), tz="UTC").tz_convert(NY)
        return self._et

    def time_between(self, start, end):
        """Mask of bars whose OPEN time is in [start, end) on the New York clock, within one trading day
        (18:00 -> 16:15), e.g. time_between('09:30', '11:00') or time_between('18:00', '09:30')."""
        a = tmin_of(start)
        b = TMIN_DAY_END if hm(end) == MOD_DAY_END else tmin_of(end)
        if b <= a:
            raise ValueError("end must be later than start inside the trading day (18:00 -> 16:15 ET)")
        return (self.tmin >= a) & (self.tmin < b)

    def opens_at(self, clock):
        """Mask of bars that OPEN at this New York time, e.g. opens_at('09:30')."""
        return self.mod == hm(clock)

    def ends_at(self, clock):
        """Mask of bars whose nominal END is this New York time, e.g. ends_at('10:00') is the 09:55 five-minute bar:
        a signal there is acted on from 10:00."""
        return self.tmin_end == (TMIN_DAY_END if hm(clock) == MOD_DAY_END else tmin_of(clock))

    def truncate(self, k):
        """The first k bars as a new Bars object (the incomplete-day flags are kept as they are).  Used by the
        no-lookahead check."""
        k = int(k)
        if not 1 <= k <= self.n:
            raise ValueError("k out of range")
        return Bars(self.t[:k], self.o[:k], self.h[:k], self.l[:k], self.c[:k], self.res, tmin_end=self.tmin_end[:k],
                    incomplete=self.incomplete[:k], rth_counts=self._rth_counts, source=self.source)

    def frame(self, i0=0, i1=None):
        """A small DataFrame of bars i0..i1-1 for eyeballing."""
        i1 = self.n if i1 is None else i1
        s = slice(i0, i1)
        return pd.DataFrame({"et": self.et[s], "o": self.o[s], "h": self.h[s], "l": self.l[s], "c": self.c[s],
                             "tday": self.tday[s], "rth": self.rth[s], "incomplete": self.incomplete[s]},
                            index=np.arange(self.n)[s])

    def _lists(self):
        if self._lists_cache is None:
            self._lists_cache = {
                "o": _dbl(self.o), "h": _dbl(self.h), "l": _dbl(self.l), "c": _dbl(self.c),
                "tday": _i64(self.tday_id), "tmin_end": _i64(self.tmin_end),
            }
        return self._lists_cache

    def __repr__(self):
        return (f"Bars(n={self.n}, res={self.res}m, {self.et[0]} .. {self.et[-1]}, days={len(self.days)}, "
                f"source={self.source!r})")


# ---- loading ----------------------------------------------------------------------------------------------------
_CACHE = {}


def _load_npz(path):
    with np.load(path) as z:
        return {k: z[k] for k in ("t", "o", "h", "l", "c")}


def rth_counts(t_1m):
    """(tday_id, count): number of regular-session (09:30-16:00 ET) bars per New York date in an array of 1-MINUTE
    bar open times.  Pass the result to Bars(..., rth_counts=...) to get the incomplete-day flags."""
    loc = local_seconds(t_1m)
    mod = (loc % 86400) // 60
    m = (mod >= MOD_RTH_OPEN) & (mod < MOD_RTH_CLOSE)
    ids, cnt = np.unique((loc // 86400)[m], return_counts=True)
    return _ro(ids.astype("int64")), _ro(cnt.astype("int64"))


def rth_counts_1m():
    """rth_counts() of NSX_1m.npz (cached).  This is the source of the incomplete-day flag for EVERY resolution."""
    if "counts" not in _CACHE:
        with np.load(FILE_1M) as z:
            t = z["t"]
        _CACHE["counts"] = rth_counts(t)
    return _CACHE["counts"]


def compute_split():
    """Recompute the fixed split from NSX_1m.npz.  Returns a dict; the unit tests check it equals the constants."""
    ids, cnt = rth_counts_1m()
    comp = ids[cnt >= MIN_RTH_1M_BARS]
    n = len(comp)
    n_is = int(n * IS_FRACTION)
    d = comp.astype("datetime64[D]")
    return {"n_complete_days": n, "n_is_days": n_is, "n_oos_days": n - n_is, "split_date": str(d[n_is]),
            "first_day": str(d[0]), "last_day": str(d[-1]), "last_is_day": str(d[n_is - 1])}


def _drop_after_day_end(a):
    """Remove bars that open at or after 16:15 ET and before 18:00 ET."""
    mod = (local_seconds(a["t"]) % 86400) // 60
    keep = (mod < MOD_DAY_END) | (mod >= MOD_DAY_START)
    return {k: v[keep] for k, v in a.items()}


def load_bars(res=5, anchor="00:00"):
    """Load the Nasdaq-100 bars at `res` minutes.  res=5 reads NSX_5m.npz, res=1 reads NSX_1m.npz, any other value
    resamples the 1-minute bars (buckets aligned to the New York clock, shifted by `anchor`, e.g. anchor='09:30' for
    60-minute bars that start at 09:30).  Bars that open at or after 16:15 ET are dropped.  Cached per process."""
    res = int(res)
    key = ("bars", res, hm(anchor) % res)
    if key not in _CACHE:
        counts = rth_counts_1m()
        if res == 5 and hm(anchor) % 5 == 0:
            a = _drop_after_day_end(_load_npz(FILE_5M))
            b = Bars(a["t"], a["o"], a["h"], a["l"], a["c"], 5, rth_counts=counts, source=FILE_5M)
        else:
            a = _load_npz(FILE_1M)
            if res == 1:
                a = _drop_after_day_end(a)
                b = Bars(a["t"], a["o"], a["h"], a["l"], a["c"], 1, rth_counts=counts, source=FILE_1M)
            else:
                r = resample_1m(a["t"], a["o"], a["h"], a["l"], a["c"], res, anchor)
                b = Bars(r["t"], r["o"], r["h"], r["l"], r["c"], res, tmin_end=r["tmin_end"], rth_counts=counts,
                         source=f"{FILE_1M} (resampled to {res} min, anchor {hm(anchor) % res} min)")
        _CACHE[key] = b
    return _CACHE[key]


# =====================================================================================================================
# 3. RESAMPLING
# =====================================================================================================================
def resample_1m(t, o, h, l, c, minutes, anchor="00:00"):
    """Resample 1-minute bars to `minutes`-minute bars.

    Buckets are aligned to the New York clock: a bucket starts at anchor + k * minutes (anchor default midnight).
    1-minute bars that open at or after 16:15 ET (and before 18:00 ET) are dropped first, and a bucket never mixes two
    trading days: if a bucket straddles the 16:15-18:00 break, the evening part becomes its own bar stamped 18:00.
    When `minutes` does not divide a day (7, 50, 65, 130, 195, 390, ...) the grid starts again at midnight: the last
    bucket of the evening ends at 00:00 and the first bucket of the new calendar day starts at 00:00.
    Returns dict(t, o, h, l, c, tmin_end); t is the bucket start (epoch seconds UTC), tmin_end the nominal bucket end
    in minutes since 18:00, capped at 16:15 (1335).
    """
    n_min = int(minutes)
    if n_min < 1:
        raise ValueError("minutes must be >= 1")
    t = np.asarray(t, dtype="int64")
    if (t % 60 != 0).any():
        raise ValueError("1-minute bar times must be whole minutes")
    o, h, l, c = (np.asarray(x, dtype="float64") for x in (o, h, l, c))
    loc = local_seconds(t)
    mod = (loc % 86400) // 60
    keep = (mod < MOD_DAY_END) | (mod >= MOD_DAY_START)
    t, o, h, l, c, mod = t[keep], o[keep], h[keep], l[keep], c[keep], mod[keep]
    a = hm(anchor) % n_min
    b0 = ((mod - a) // n_min) * n_min + a           # bucket start, minute of day (can be < 0: starts the day before)
    evening = mod >= MOD_DAY_START
    b = np.where(evening & (b0 < MOD_DAY_START), MOD_DAY_START, b0)
    e = b0 + n_min                                   # nominal bucket end, minute of day (can be > 1440: next day)
    if 1440 % n_min:
        # The grid anchor + k * minutes does not repeat from one calendar day to the next, so it starts again at
        # midnight and no bucket may cross midnight: without this the last evening bar "ended" after the next bar
        # had opened and the first bar after midnight was stamped before midnight (out of order for some anchors).
        b = np.maximum(b, 0)
        e = np.minimum(e, 1440)
    bt = t - (mod - b) * 60                          # bucket start in epoch seconds (same for all bars of a bucket)
    starts = np.flatnonzero(np.r_[True, bt[1:] != bt[:-1]])
    ends = np.r_[starts[1:] - 1, len(t) - 1]
    tmin_b = (b[starts] - MOD_DAY_START) % 1440
    tmin_e = np.minimum(tmin_b + (e[starts] - b[starts]), TMIN_DAY_END)
    return {"t": bt[starts], "o": o[starts], "h": np.maximum.reduceat(h, starts), "l": np.minimum.reduceat(l, starts),
            "c": c[ends], "tmin_end": tmin_e}


# =====================================================================================================================
# 4. INDICATOR HELPERS  (vectorized; the value at bar i uses bars <= i only; NaN until enough history exists)
# =====================================================================================================================
def _f(x):
    return np.asarray(x, dtype="float64")


def _first_valid(x):
    v = ~np.isnan(x)
    return int(np.argmax(v)) if v.any() else -1


def lag(x, k=1):
    """x shifted k bars into the past (out[i] = x[i-k]); k must be >= 0, so it can never look ahead."""
    k = int(k)
    if k < 0:
        raise ValueError("lag(k) with k < 0 would look ahead")
    x = _f(x)
    out = np.full(len(x), np.nan)
    if k < len(x):
        out[k:] = x[:len(x) - k]
    return out


def sma(x, n):
    """Simple moving average of the last n values (NaN for the first n-1 bars or while a NaN is in the window)."""
    return pd.Series(_f(x)).rolling(int(n), min_periods=int(n)).mean().to_numpy()


def rolling_std(x, n, ddof=0):
    """Standard deviation of the last n values (population, ddof=0, by default - the Bollinger convention)."""
    return pd.Series(_f(x)).rolling(int(n), min_periods=int(n)).std(ddof=ddof).to_numpy()


def rolling_max(x, n):
    """Highest of the last n values, including the current bar."""
    return pd.Series(_f(x)).rolling(int(n), min_periods=int(n)).max().to_numpy()


def rolling_min(x, n):
    """Lowest of the last n values, including the current bar."""
    return pd.Series(_f(x)).rolling(int(n), min_periods=int(n)).min().to_numpy()


def ema(x, n):
    """Exponential moving average, alpha = 2/(n+1), seeded with the first value, NaN for the first n-1 bars
    (same numbers as pandas ewm(span=n, adjust=False, min_periods=n))."""
    x = _f(x)
    n = int(n)
    out = np.full(len(x), np.nan)
    f = _first_valid(x)
    if f < 0 or len(x) - f < n:
        return out
    a = 2.0 / (n + 1.0)
    y = _lfilter([a], [1.0, -(1.0 - a)], x[f:], zi=[(1.0 - a) * x[f]])[0]
    out[f + n - 1:] = y[n - 1:]
    return out


def wilder(x, n):
    """Wilder smoothing: the first value is the plain mean of the first n values, then y += (x - y) / n."""
    x = _f(x)
    n = int(n)
    out = np.full(len(x), np.nan)
    f = _first_valid(x)
    if f < 0 or len(x) - f < n:
        return out
    seed = x[f:f + n].mean()
    out[f + n - 1] = seed
    if len(x) > f + n:
        a = 1.0 / n
        out[f + n:] = _lfilter([a], [1.0, -(1.0 - a)], x[f + n:], zi=[(1.0 - a) * seed])[0]
    return out


def true_range(h, l, c):
    """True range; the first bar has no previous close and uses high - low."""
    h, l, c = _f(h), _f(l), _f(c)
    pc = lag(c, 1)
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    tr[0] = h[0] - l[0]
    return tr


def atr(h, l, c, n=14):
    """Wilder average true range over bars (it spans the overnight break like any bar series)."""
    return wilder(true_range(h, l, c), n)


def rsi(c, n=14):
    """Wilder RSI (0..100).  100 when there were no losses in the window, 50 when there was no movement at all."""
    c = _f(c)
    d = np.diff(c, prepend=np.nan)
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    up[np.isnan(d)] = np.nan
    dn[np.isnan(d)] = np.nan
    au, ad = wilder(up, n), wilder(dn, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100.0 - 100.0 / (1.0 + au / ad)
    out = np.where(ad == 0, np.where(au == 0, 50.0, 100.0), out)
    out[np.isnan(au)] = np.nan
    return out


def adx(h, l, c, n=14):
    """Wilder ADX.  Returns (adx, plus_di, minus_di); DI values start at bar n, ADX at bar 2n-1."""
    h, l, c = _f(h), _f(l), _f(c)
    up = np.diff(h, prepend=np.nan)
    dn = -np.diff(l, prepend=np.nan)
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = true_range(h, l, c)
    pdm[0] = mdm[0] = tr[0] = np.nan
    s_tr, s_p, s_m = wilder(tr, n), wilder(pdm, n), wilder(mdm, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = 100.0 * s_p / s_tr
        mdi = 100.0 * s_m / s_tr
        dx = 100.0 * np.abs(pdi - mdi) / (pdi + mdi)
    dx = np.where((pdi + mdi) == 0, 0.0, dx)
    dx[np.isnan(pdi)] = np.nan
    return wilder(dx, n), pdi, mdi


def bollinger(x, n=20, k=2.0, ddof=0):
    """Bollinger bands.  Returns (mid, upper, lower) = SMA(n) and SMA +/- k * rolling std."""
    mid = sma(x, n)
    sd = rolling_std(x, n, ddof)
    return mid, mid + k * sd, mid - k * sd


def keltner(h, l, c, n=20, atr_n=10, mult=2.0):
    """Keltner channels.  Returns (mid, upper, lower) = EMA(close, n) and EMA +/- mult * Wilder ATR(atr_n)."""
    mid = ema(c, n)
    a = atr(h, l, c, atr_n)
    return mid, mid + mult * a, mid - mult * a


def donchian(h, l, n, include_current=True):
    """Donchian channel.  Returns (highest high, lowest low) of the last n bars.  include_current=False uses the n
    bars BEFORE the current one (the usual breakout level: a bar can then close beyond it)."""
    hi, lo = rolling_max(h, n), rolling_min(l, n)
    if not include_current:
        hi, lo = lag(hi, 1), lag(lo, 1)
    return hi, lo


def cross_above(a, b):
    """True on the bar where a moves from <= b to > b."""
    a, b = np.broadcast_arrays(_f(a), _f(b))
    out = np.zeros(len(a), dtype=bool)
    out[1:] = (a[1:] > b[1:]) & (a[:-1] <= b[:-1])
    return out


def cross_below(a, b):
    """True on the bar where a moves from >= b to < b."""
    a, b = np.broadcast_arrays(_f(a), _f(b))
    out = np.zeros(len(a), dtype=bool)
    out[1:] = (a[1:] < b[1:]) & (a[:-1] >= b[:-1])
    return out


def masked(mask, fn, *arrays, ffill=False):
    """Run an indicator on the bars where mask is True only (for example regular-session bars), and put the results
    back at those bars; other bars are NaN, or carry the last value forward with ffill=True.  fn may return one array
    or a tuple of arrays."""
    mask = np.asarray(mask, dtype=bool)
    res = fn(*[np.asarray(a)[mask] for a in arrays])
    single = not isinstance(res, tuple)
    outs = []
    for r in ((res,) if single else res):
        out = np.full(len(mask), np.nan)
        out[mask] = r
        if ffill:
            out = pd.Series(out).ffill().to_numpy()
        outs.append(out)
    return outs[0] if single else tuple(outs)


# ---- session helpers (take a Bars object) ---------------------------------------------------------------------------
def _prev_day(valid):
    """For each row of the day table: index of the most recent EARLIER row where valid is True, or -1."""
    idx = np.where(valid, np.arange(len(valid)), -1)
    run = np.maximum.accumulate(idx)
    return np.r_[-1, run[:-1]]


def lag_days_to_bars(bars, per_day, valid=None):
    """Spread a per-trading-day array (aligned with bars.days) over the bars WITHOUT lookahead: every bar of trading
    day d gets the value of the most recent earlier trading day for which `valid` is True (default: days that have a
    regular session).  NaN when there is no such day."""
    per_day = _f(per_day)
    if len(per_day) != len(bars.days):
        raise ValueError("per_day must have one value per row of bars.days")
    valid = (bars.days["rth_first"].to_numpy() >= 0) if valid is None else np.asarray(valid, dtype=bool)
    p = _prev_day(valid)
    v = np.where(p >= 0, per_day[np.maximum(p, 0)], np.nan)
    return v[bars.day_idx]


def prior_rth(bars, require_complete=True):
    """Open, high, low and close of the PRIOR regular session (09:30-16:00 ET): the most recent earlier trading day
    that has regular-session bars.  Constant over the whole trading day (from the 18:00 evening open on).  With
    require_complete=True (default) the values are NaN when that prior session is incomplete (holiday half days,
    source gaps), so rules built on them do not trade on unreliable levels.  Returns a dict of arrays."""
    d = bars.days
    has = d["rth_first"].to_numpy() >= 0
    p = _prev_day(has)
    ok = p >= 0
    if require_complete:
        ok &= d["complete"].to_numpy()[np.maximum(p, 0)]
    out = {}
    for k in ("open", "high", "low", "close"):
        v = np.where(ok, d["rth_" + k].to_numpy()[np.maximum(p, 0)], np.nan)
        out[k] = v[bars.day_idx]
    return out


def _day_group_cum(bars, values, mask, how):
    """Running max/min/sum of `values` over the bars of each trading day where mask is True, carried forward to the
    end of the trading day; NaN before the first masked bar of the day."""
    s = pd.Series(np.where(mask, values, np.nan))
    g = s.groupby(bars.day_idx)
    run = g.cummax() if how == "max" else g.cummin() if how == "min" else g.cumsum()
    return run.groupby(bars.day_idx).ffill().to_numpy()


def overnight_range(bars):
    """High and low of the overnight session (18:00-09:30 ET) of the bar's trading day, using bars <= i: a running
    extreme while the overnight session is in progress, then fixed from 09:30 on.  Returns (high, low)."""
    m = (bars.tmin < TMIN_RTH_OPEN) & (bars.tmin_end <= TMIN_RTH_OPEN)
    return _day_group_cum(bars, bars.h, m, "max"), _day_group_cum(bars, bars.l, m, "min")


def session_high_low(bars, start="09:30"):
    """Running high and low since `start` (ET) of the bar's trading day, including the current bar.  NaN before
    `start`.  Returns (high, low)."""
    m = bars.tmin >= tmin_of(start)
    return _day_group_cum(bars, bars.h, m, "max"), _day_group_cum(bars, bars.l, m, "min")


def opening_range(bars, start="09:30", minutes=30, require_full=True):
    """High and low of the window [start, start + minutes) of the bar's trading day.  The values appear on the bar
    that completes the window (so a signal on that bar's close may use them) and stay to the end of the trading day;
    NaN before, and NaN all day when the window has no bars - or, with require_full=True (default), when any bar of
    the window is missing.  `minutes` should be a multiple of the bar length.  Returns (high, low)."""
    a = tmin_of(start)
    b = a + int(minutes)
    win = (bars.tmin >= a) & (bars.tmin_end <= b)
    nd = len(bars.days)
    hi = np.full(nd, np.nan); lo = np.full(nd, np.nan)
    cnt = np.bincount(bars.day_idx[win], minlength=nd)
    wi = np.flatnonzero(win)
    if len(wi):
        wd_ = bars.day_idx[wi]
        st = np.flatnonzero(np.r_[True, wd_[1:] != wd_[:-1]])
        hi[wd_[st]] = np.maximum.reduceat(bars.h[wi], st)
        lo[wd_[st]] = np.minimum.reduceat(bars.l[wi], st)
    if require_full:
        full = cnt * bars.res == int(minutes)
        hi[~full] = np.nan
        lo[~full] = np.nan
    avail = bars.tmin_end >= b
    return np.where(avail, hi[bars.day_idx], np.nan), np.where(avail, lo[bars.day_idx], np.nan)


def rth_open(bars, max_late_min=5):
    """Open of the regular session (open of its first bar) of the bar's trading day, from that bar on; NaN before
    09:30, and NaN all day when the first regular-session bar opens more than max_late_min after 09:30."""
    d = bars.days
    rf = d["rth_first"].to_numpy()
    ok = (rf >= 0) & (d["rth_first_mod"].to_numpy() <= MOD_RTH_OPEN + max_late_min)
    v = np.where(ok, d["rth_open"].to_numpy(), np.nan)[bars.day_idx]
    return np.where(np.arange(bars.n) >= rf[bars.day_idx], v, np.nan)


def gap(bars, pct=False, require_complete=True, max_late_min=5):
    """Opening gap: regular-session open minus the prior regular-session close, in points (or as a fraction of the
    prior close with pct=True).  Available from the first regular-session bar on; NaN before."""
    ro = rth_open(bars, max_late_min)
    pc = prior_rth(bars, require_complete)["close"]
    g = ro - pc
    return g / pc if pct else g


def floor_pivots(bars, require_complete=True):
    """Classic floor-trader pivots from the prior regular session's high, low, close.  Dict with P, R1-R3, S1-S3."""
    p = prior_rth(bars, require_complete)
    H, L, C = p["high"], p["low"], p["close"]
    P = (H + L + C) / 3.0
    return {"P": P, "R1": 2 * P - L, "S1": 2 * P - H, "R2": P + (H - L), "S2": P - (H - L),
            "R3": H + 2 * (P - L), "S3": L - 2 * (H - P)}


def camarilla_pivots(bars, require_complete=True):
    """Camarilla levels from the prior regular session: close +/- range * 1.1 / (12, 6, 4, 2).  Dict R1-R4, S1-S4."""
    p = prior_rth(bars, require_complete)
    C, R = p["close"], p["high"] - p["low"]
    out = {}
    for k, div in ((1, 12.0), (2, 6.0), (3, 4.0), (4, 2.0)):
        out[f"R{k}"] = C + R * 1.1 / div
        out[f"S{k}"] = C - R * 1.1 / div
    return out


def daily_atr(bars, n=14, method="wilder"):
    """Daily ATR from regular sessions.  Daily bars are the COMPLETE regular sessions (high, low, close of 09:30-16:00
    ET); true range uses the previous complete session's close; method 'wilder' or 'sma'.  Every bar of trading day d
    gets the ATR as of the last complete session before d, so there is no lookahead."""
    d = bars.days
    ok = d["complete"].to_numpy() & (d["rth_first"].to_numpy() >= 0)
    per_day = np.full(len(d), np.nan)
    if ok.any():
        H, L, C = (d[k].to_numpy()[ok] for k in ("rth_high", "rth_low", "rth_close"))
        tr = true_range(H, L, C)
        per_day[ok] = wilder(tr, n) if method == "wilder" else sma(tr, n)
    return lag_days_to_bars(bars, per_day, valid=ok)


def twap_vwap_proxy(bars, anchor="09:30", bands=False):
    """TIME-weighted average of typical price (h+l+c)/3 since `anchor` (ET) of the bar's trading day - a VWAP PROXY
    ONLY: the data has no volume, so this is NOT a true VWAP (every bar has equal weight).  NaN before the anchor.
    With bands=True returns (twap, sd) where sd is the running population standard deviation of typical price around
    its running mean since the anchor."""
    tp = (bars.h + bars.l + bars.c) / 3.0
    m = bars.tmin >= tmin_of(anchor)
    ref = pd.Series(np.where(m, tp, np.nan)).groupby(bars.day_idx).transform("first").to_numpy()
    x = np.where(m, tp - ref, 0.0)                    # deviations from the day's first value keep the sums small
    g = bars.day_idx
    cnt = pd.Series(m.astype("float64")).groupby(g).cumsum().to_numpy()
    s1 = pd.Series(x).groupby(g).cumsum().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        mean = np.where(m, s1 / cnt, np.nan)
        tw = mean + ref
        if not bands:
            return tw
        s2 = pd.Series(x * x).groupby(g).cumsum().to_numpy()
        var = np.where(m, s2 / cnt - mean * mean, np.nan)
    return tw, np.sqrt(np.maximum(var, 0.0))


# =====================================================================================================================
# 5. SIMULATOR
# =====================================================================================================================
# One bar-by-bar state machine serves both strategy paths, so fills are identical by construction:
#   path (a)  Signals   - precomputed arrays (fast: idle stretches are skipped)
#   path (b)  Callback  - a function called after every closed bar (for path-dependent logic)
#
# Order of events inside bar j:
#   1. a position flagged for a signal exit is closed at the open of j
#   2. if flat, pending entry orders are tried (market: the open; stop / limit: the bar's range)
#   3. if in a position: protective stop first, then first target and target (not on the entry bar of a stop or
#      limit entry, where only the stop counts)
#   4. at the close of j: time exit, bar-count exit, end-of-day exit; otherwise stop management (first-target stop
#      move, breakeven, trailing), exit signals, then new entry signals / the callback.  Everything decided at the
#      close of j takes effect from bar j+1.

@dataclass(frozen=True)
class Session:
    """Session rules.  The defaults are the intraday rules that are usable on a Tradeify account.

    last_entry          no entry is ever filled after this ET time.  A market order needs a bar that OPENS at or before
                        it; a stop or limit order (which can fill anywhere inside a bar) needs a bar that ENDS at or
                        before it.  None = no limit other than the end of the trading day.
    first_entry         optional earliest ET time: an entry needs a bar that opens at or after it.
    allow_multi_day     False (default): every position is closed at the close of the last bar that ends by 16:10 ET,
                        pending orders die there, nothing is carried across the end of the trading day.
                        True: swing mode, positions and (with expiry_bars) orders may run across days; such a test is
                        flagged tradeify_usable = False.
    max_trades_per_day  maximum number of entries per trading day (None = no limit).
    Entries are never filled on incomplete days (fewer than 370 regular-session 1-minute bars), in either mode.
    """
    last_entry: str | None = "15:55"
    first_entry: str | None = None
    allow_multi_day: bool = False
    max_trades_per_day: int | None = None

    def __post_init__(self):
        if self.last_entry is not None:
            hm(self.last_entry)
        if self.first_entry is not None:
            hm(self.first_entry)
        if self.max_trades_per_day is not None and int(self.max_trades_per_day) < 1:
            raise ValueError("max_trades_per_day must be >= 1 or None")


@dataclass(frozen=True)
class TradeRules:
    """Trade management applied to every trade of a run (orders may override the per-order ones).

    exit_time          close at the close of the last bar that ends by this ET time ('HH:MM'); reason 'time'
    max_bars           close at the close of the N-th bar held, the entry bar being bar 1; reason 'bars'
    tp1_frac           fraction of the position closed at the first target (when an order has tp1 / tp1_pts / tp1_r)
    tp1_stop           what happens to the stop after the first target: 'be' = move to the entry price, a number x =
                       move to entry + x points in the trade's favour, 'keep' = leave it
    be_trigger_pts/_r  when the best price since entry (closed bars) is this many points / R in profit, move the stop
                       to entry + be_offset_pts (in the trade's favour)
    trail_pts/_r       trail the stop this many points / R behind the best price since entry (closed bars);
    trail_trigger_pts/_r   ... only once the trade has been this far in profit (default: from the start)
    Stops are only ever tightened by these rules, and a change made at the close of a bar counts from the next bar.
    """
    exit_time: str | None = None
    max_bars: int | None = None
    tp1_frac: float = 0.5
    tp1_stop: object = "be"
    be_trigger_pts: float | None = None
    be_trigger_r: float | None = None
    be_offset_pts: float = 0.0
    trail_pts: float | None = None
    trail_r: float | None = None
    trail_trigger_pts: float | None = None
    trail_trigger_r: float | None = None

    def __post_init__(self):
        if self.exit_time is not None:
            hm(self.exit_time)
        if self.max_bars is not None and int(self.max_bars) < 1:
            raise ValueError("max_bars must be >= 1")
        if not 0.0 < float(self.tp1_frac) < 1.0:
            raise ValueError("tp1_frac must be between 0 and 1")
        _tp1_stop_value(self.tp1_stop)
        for k in ("be_trigger_pts", "be_trigger_r", "trail_pts", "trail_r", "trail_trigger_pts", "trail_trigger_r"):
            v = getattr(self, k)
            if v is not None and not float(v) > 0:
                raise ValueError(f"{k} must be > 0")


def _tp1_stop_value(x):
    if x is None or x == "keep":
        return None
    if x == "be":
        return 0.0
    v = float(x)
    if v != v:
        raise ValueError("tp1_stop must be 'be', 'keep' or a number of points")
    return v


# internal order record: a plain list, fields by index (fast to copy)
(_SIDE, _TYP, _PRICE, _STOP, _STOP_PTS, _TGT, _TGT_PTS, _TGT_R, _TP1, _TP1_PTS, _TP1_R, _TP1_FRAC, _TP1_STOP,
 _LAST, _EXP_TMIN, _DAY, _MAXB, _BE_PTS, _BE_R, _BE_OFF, _TR_PTS, _TR_R, _TRG_PTS, _TRG_R, _SIG) = range(25)

# per-order values a strategy may give: name -> (index, must be > 0, integer)
_ORDER_FIELDS = {
    "price": (_PRICE, False, False), "stop": (_STOP, False, False), "stop_pts": (_STOP_PTS, True, False),
    "target": (_TGT, False, False), "target_pts": (_TGT_PTS, True, False), "target_r": (_TGT_R, True, False),
    "tp1": (_TP1, False, False), "tp1_pts": (_TP1_PTS, True, False), "tp1_r": (_TP1_R, True, False),
    "max_bars": (_MAXB, True, True), "trail_pts": (_TR_PTS, True, False), "be_trigger_pts": (_BE_PTS, True, False),
}
_SIDE_KEYS = ("entry", "order", "exit", "trail", "expiry_bars", "expiry_time") + tuple(_ORDER_FIELDS)
_INF = float("inf")


def _order_template(rules):
    od = [None] * 25
    od[_SIDE] = 0; od[_TYP] = MARKET; od[_PRICE] = float("nan")
    od[_TP1_FRAC] = float(rules.tp1_frac); od[_TP1_STOP] = _tp1_stop_value(rules.tp1_stop)
    od[_LAST] = _BIG; od[_EXP_TMIN] = 9999; od[_DAY] = -1; od[_SIG] = -1
    od[_MAXB] = None if rules.max_bars is None else int(rules.max_bars)
    od[_BE_PTS] = rules.be_trigger_pts; od[_BE_R] = rules.be_trigger_r; od[_BE_OFF] = float(rules.be_offset_pts)
    od[_TR_PTS] = rules.trail_pts; od[_TR_R] = rules.trail_r
    od[_TRG_PTS] = rules.trail_trigger_pts; od[_TRG_R] = rules.trail_trigger_r
    return od


def _check_structure(has, what):
    """has: set of field names that are given for one order / side."""
    if "stop" in has and "stop_pts" in has:
        raise ValueError(f"{what}: give stop (a price) or stop_pts (points from the fill), not both")
    if len(has & {"target", "target_pts", "target_r"}) > 1:
        raise ValueError(f"{what}: give only one of target, target_pts, target_r")
    if len(has & {"tp1", "tp1_pts", "tp1_r"}) > 1:
        raise ValueError(f"{what}: give only one of tp1, tp1_pts, tp1_r")
    if not (has & {"stop", "stop_pts"}):
        need = has & {"target_r", "tp1_r", "be_trigger_r", "trail_r", "trail_trigger_r"}
        if need:
            raise ValueError(f"{what}: {sorted(need)} are multiples of the initial risk and need stop or stop_pts")


class Signals:
    """Path (a): the strategy as precomputed arrays (one value per bar; a signal on bar i is acted on from bar i+1).

    Simple form - one direction array, shared order fields:
        Signals(direction, order='stop', price=..., stop=..., target=..., expiry_bars=3, exit_time='15:30')
      direction   +1 = long signal, -1 = short signal, 0 = nothing, evaluated at the close of each bar
      order       'market' | 'stop' | 'limit' (or an int array of MARKET / STOP / LIMIT per bar)
      price       stop / limit price of the entry order (array)
      stop        protective stop as a PRICE        or  stop_pts    points from the actual fill price
      target      profit target as a PRICE          or  target_pts  points from the fill   or  target_r  R multiple
      tp1 / tp1_pts / tp1_r   optional first target; tp1_frac of the position is closed there (see TradeRules)
      expiry_bars the entry order may fill in the next N bars (market orders: always the next bar only)
      expiry_time the entry order may fill only in bars that end by this ET time ('HH:MM')
                  with neither, a stop / limit order works until the end of its trading day
      exit_long / exit_short   bool arrays: a True at the close of bar i closes that position at the open of bar i+1
      trail_long / trail_short float arrays of stop prices: after each closed bar the stop is tightened to this value

    Two-sided form - separate dicts for the two sides (both may be live at once; the first to fill cancels the other):
        Signals(long=dict(entry=mask, order='stop', price=hi, stop=lo), short=dict(entry=mask, order='stop', price=lo,
                stop=hi), ...)
      keys: entry (bool array, required), exit, trail, and any order field above; missing keys use the shared values.

    Every order field may be a scalar or an array (read at the signal bar).  A NaN in any field that was given voids
    that signal (use +/-inf for "none on this bar").  The remaining keyword arguments are the TradeRules and Session
    fields (exit_time, max_bars, tp1_frac, tp1_stop, be_*, trail_*, last_entry, first_entry, allow_multi_day,
    max_trades_per_day).
    """

    def __init__(self, direction=None, *, long=None, short=None, order="market", price=None, stop=None, stop_pts=None,
                 target=None, target_pts=None, target_r=None, tp1=None, tp1_pts=None, tp1_r=None,
                 expiry_bars=None, expiry_time=None, exit_long=None, exit_short=None, trail_long=None, trail_short=None,
                 exit_time=None, max_bars=None, tp1_frac=0.5, tp1_stop="be",
                 be_trigger_pts=None, be_trigger_r=None, be_offset_pts=0.0,
                 trail_pts=None, trail_r=None, trail_trigger_pts=None, trail_trigger_r=None,
                 last_entry="15:55", first_entry=None, allow_multi_day=False, max_trades_per_day=None):
        shared = {"order": order, "price": price, "stop": stop, "stop_pts": stop_pts, "target": target,
                  "target_pts": target_pts, "target_r": target_r, "tp1": tp1, "tp1_pts": tp1_pts, "tp1_r": tp1_r,
                  "expiry_bars": expiry_bars, "expiry_time": expiry_time}
        # max_bars, trail_pts, be_trigger_pts: a scalar is a run-level rule, an array is a per-signal value
        rule_kw = {}
        for k, v in (("max_bars", max_bars), ("trail_pts", trail_pts), ("be_trigger_pts", be_trigger_pts)):
            if v is not None and np.ndim(v) > 0:
                shared[k] = v
                rule_kw[k] = None
            else:
                rule_kw[k] = v
        if direction is not None:
            if long is not None or short is not None:
                raise ValueError("give either direction or long= / short=, not both")
            d = np.asarray(direction, dtype="float64")
            long = {"entry": d > 0}
            short = {"entry": d < 0}
        elif long is None and short is None:
            raise ValueError("give a direction array, or long= and/or short= dicts")
        sides = {}
        for s, d, ex, tr in ((1, long, exit_long, trail_long), (-1, short, exit_short, trail_short)):
            if d is None:
                sides[s] = None
                continue
            d = dict(d)
            bad = set(d) - set(_SIDE_KEYS)
            if bad:
                raise ValueError(f"unknown keys in side dict: {sorted(bad)}")
            if "entry" not in d:
                raise ValueError("a side dict needs an 'entry' array")
            own = {k for k in d if k in _ORDER_FIELDS and d[k] is not None}
            for group in (("stop", "stop_pts"), ("target", "target_pts", "target_r"), ("tp1", "tp1_pts", "tp1_r")):
                if own & set(group):                 # a side's own choice replaces the shared one of the same group
                    for k in group:
                        d.setdefault(k, None)
            for k, v in shared.items():
                d.setdefault(k, v)
            d.setdefault("exit", ex)
            d.setdefault("trail", tr)
            sides[s] = d
        self.sides = sides
        self.rules = TradeRules(exit_time=exit_time, max_bars=rule_kw["max_bars"], tp1_frac=tp1_frac, tp1_stop=tp1_stop,
                                be_trigger_pts=rule_kw["be_trigger_pts"], be_trigger_r=be_trigger_r,
                                be_offset_pts=be_offset_pts, trail_pts=rule_kw["trail_pts"], trail_r=trail_r,
                                trail_trigger_pts=trail_trigger_pts, trail_trigger_r=trail_trigger_r)
        self.session = Session(last_entry=last_entry, first_entry=first_entry, allow_multi_day=bool(allow_multi_day),
                               max_trades_per_day=max_trades_per_day)


_UNSET = object()


class Context:
    """What a path (b) callback sees and can do.  The engine calls on_bar(ctx) after every closed bar.

    State (read only; refreshed before each call)
      i              index of the bar that just closed - use bars arrays at indices <= i only
      bars           the Bars object
      position       +1 long, -1 short, 0 flat
      entry_price, entry_bar, stop, target, bars_held, mfe, mae (points, closed bars), open_pts (close - entry, signed)
      risk           initial risk in points (entry fill to initial stop), NaN without a stop
      exiting        True when the position will be closed at the next open (ctx.exit() was called)
      pending_long, pending_short     True while an entry order of that side is waiting
      trades_today   entries filled so far in the current trading day;  net_today  their closed net points
      n_trades       closed trades so far;  user  a dict for the strategy's own state

    Actions (all take effect from the next bar)
      buy_market / sell_market(**kw), buy_stop / sell_stop(price, **kw), buy_limit / sell_limit(price, **kw)
          kw: stop | stop_pts, target | target_pts | target_r, tp1 | tp1_pts | tp1_r, expiry_bars, expiry_time,
              max_bars, tp1_frac, tp1_stop, be_trigger_pts, be_trigger_r, be_offset_pts, trail_pts, trail_r,
              trail_trigger_pts, trail_trigger_r
          A new order replaces a waiting order of the same side; a long and a short order may wait together (the
          first to fill cancels the other).  Orders are only accepted when flat, or together with ctx.exit().
          Returns False (and places nothing) when a given value is NaN, or when the trading day has no further bar
          and the order may not be carried into the next one (see the session rules).
      cancel(side=0)        cancel waiting orders (0 = both sides, +1 long, -1 short)
      set_stop(price)       replace the protective stop (None removes it);  set_target(price) likewise
      exit()                close the position at the next bar's open (reason 'signal')
    """
    __slots__ = ("bars", "i", "position", "entry_price", "entry_bar", "stop", "target", "bars_held", "mfe", "mae",
                 "open_pts", "risk", "exiting", "pending_long", "pending_short", "trades_today", "net_today", "n_trades", "user",
                 "_dirty", "_exit", "_set_stop", "_set_tgt", "_cancel", "_ol", "_os", "_void", "_dropped", "_tmpl",
                 "_td", "_te", "_n", "_intraday")

    def __init__(self, bars, tmpl, intraday):
        self.bars = bars
        self.i = -1
        self.position = 0
        self.entry_price = self.entry_bar = self.stop = self.target = None
        self.bars_held = 0
        self.mfe = self.mae = self.open_pts = 0.0
        self.risk = float("nan")
        self.exiting = False
        self.pending_long = self.pending_short = False
        self.trades_today = 0
        self.net_today = 0.0
        self.n_trades = 0
        self.user = {}
        self._dirty = False
        self._exit = False
        self._set_stop = self._set_tgt = _UNSET
        self._cancel = 0
        self._ol = self._os = None
        self._void = 0
        self._dropped = 0
        self._tmpl = tmpl
        self._td = bars._lists()["tday"]
        self._te = bars._lists()["tmin_end"]
        self._n = bars.n
        self._intraday = intraday

    def order(self, side, order="market", price=None, *, expiry_bars=None, expiry_time=None, tp1_frac=None,
              tp1_stop=_UNSET, be_trigger_r=None, be_offset_pts=None, trail_r=None, trail_trigger_pts=None,
              trail_trigger_r=None, **fields):
        s = 1 if side > 0 else -1
        ty = _ORDER_CODES[order] if isinstance(order, str) else int(order)
        if ty not in (MARKET, STOP, LIMIT):
            raise ValueError("order must be 'market', 'stop' or 'limit'")
        if price is not None and ty != MARKET:
            fields["price"] = price
        elif ty == MARKET:
            fields.pop("price", None)       # a market order has no price
        od = self._tmpl[:]
        od[_SIDE] = s
        od[_TYP] = ty
        void = False
        has = set()
        for k, v in fields.items():
            if k not in _ORDER_FIELDS:
                raise TypeError(f"unknown order argument {k!r}")
            if v is None:
                continue
            idx, must_pos, is_int = _ORDER_FIELDS[k]
            v = float(v)
            if v != v:
                void = True
                continue
            if must_pos and not v > 0:
                raise ValueError(f"{k} must be > 0")
            od[idx] = int(v) if is_int else v
            has.add(k)
        for k, v, idx in (("be_trigger_r", be_trigger_r, _BE_R), ("trail_r", trail_r, _TR_R),
                          ("trail_trigger_pts", trail_trigger_pts, _TRG_PTS), ("trail_trigger_r", trail_trigger_r, _TRG_R)):
            if v is not None:
                if not float(v) > 0:
                    raise ValueError(f"{k} must be > 0")
                od[idx] = float(v)
        for k, idx in (("be_trigger_r", _BE_R), ("trail_r", _TR_R), ("trail_trigger_r", _TRG_R)):
            if od[idx] is not None:
                has.add(k)
        if be_offset_pts is not None:
            od[_BE_OFF] = float(be_offset_pts)
        if tp1_frac is not None:
            if not 0.0 < float(tp1_frac) < 1.0:
                raise ValueError("tp1_frac must be between 0 and 1")
            od[_TP1_FRAC] = float(tp1_frac)
        if tp1_stop is not _UNSET:
            od[_TP1_STOP] = _tp1_stop_value(tp1_stop)
        _check_structure(has, "order")
        eb = None
        if expiry_bars is not None:
            eb = int(expiry_bars)
            if eb < 1:
                raise ValueError("expiry_bars must be >= 1")
        if expiry_time is not None:
            od[_EXP_TMIN] = tmin_of(expiry_time)
        if ty != MARKET:
            p = od[_PRICE]
            if "price" not in has:
                if void:
                    self._void += 1
                    self._dirty = True
                    return False
                raise ValueError("stop and limit orders need a price")
            if p in (_INF, -_INF):
                void = True
        i = self.i
        if void or i + 1 >= self._n:
            self._void += 1 if void else 0
            self._dirty = True
            return False
        if not _finish_order(od, i, eb, self._td, self._te, self._intraday):
            self._dropped += 1
            self._dirty = True
            return False
        if s > 0:
            self._ol = od
        else:
            self._os = od
        self._dirty = True
        return True

    def buy_market(self, **kw):
        return self.order(1, MARKET, **kw)

    def sell_market(self, **kw):
        return self.order(-1, MARKET, **kw)

    def buy_stop(self, price, **kw):
        return self.order(1, STOP, price, **kw)

    def sell_stop(self, price, **kw):
        return self.order(-1, STOP, price, **kw)

    def buy_limit(self, price, **kw):
        return self.order(1, LIMIT, price, **kw)

    def sell_limit(self, price, **kw):
        return self.order(-1, LIMIT, price, **kw)

    def cancel(self, side=0):
        if side >= 0:
            self._cancel |= 1
            self._ol = None
        if side <= 0:
            self._cancel |= 2
            self._os = None
        self._dirty = True

    def set_stop(self, price):
        if price is not None:
            price = float(price)
            if price != price:
                raise ValueError("set_stop(NaN)")
        self._set_stop = price
        self._dirty = True

    def set_target(self, price):
        if price is not None:
            price = float(price)
            if price != price:
                raise ValueError("set_target(NaN)")
        self._set_tgt = price
        self._dirty = True

    def exit(self):
        self._exit = True
        self._dirty = True


class Callback:
    """Path (b): a per-bar callback strategy.

        Callback(on_bar, active=None, **rules_and_session)

    on_bar(ctx) is called after every closed bar (see Context).  `active` is an optional bool array: while the engine
    is idle (flat, nothing pending) the callback is only called on bars where active is True - a large speed-up when
    the strategy only ever acts in, say, the regular session.  While a position or an order is live it is called on
    every bar.  The keyword arguments are the TradeRules and Session fields, as for Signals.
    """

    def __init__(self, on_bar, *, active=None, exit_time=None, max_bars=None, tp1_frac=0.5, tp1_stop="be",
                 be_trigger_pts=None, be_trigger_r=None, be_offset_pts=0.0, trail_pts=None, trail_r=None,
                 trail_trigger_pts=None, trail_trigger_r=None,
                 last_entry="15:55", first_entry=None, allow_multi_day=False, max_trades_per_day=None):
        if not callable(on_bar):
            raise TypeError("on_bar must be a function taking one Context argument")
        self.on_bar = on_bar
        self.active = active
        self.rules = TradeRules(exit_time=exit_time, max_bars=max_bars, tp1_frac=tp1_frac, tp1_stop=tp1_stop,
                                be_trigger_pts=be_trigger_pts, be_trigger_r=be_trigger_r, be_offset_pts=be_offset_pts,
                                trail_pts=trail_pts, trail_r=trail_r, trail_trigger_pts=trail_trigger_pts,
                                trail_trigger_r=trail_trigger_r)
        self.session = Session(last_entry=last_entry, first_entry=first_entry, allow_multi_day=bool(allow_multi_day),
                               max_trades_per_day=max_trades_per_day)


def _finish_order(od, i, eb, TD, TE, intraday):
    """Set the life of an order created at the close of bar i (first live bar i+1).  Returns False when the order
    cannot be placed: in intraday mode nothing is carried from one trading day into the next, with one exception -
    an order decided on the bar that ends at 16:15 ET (the scheduled end of the trading day) is an order for the
    next trading day, which starts at 18:00 ET.  A trading day whose data stops early (half day, source gap) does
    not hand its orders to the next day."""
    if intraday and TD[i + 1] != TD[i] and TE[i] < TMIN_DAY_END:
        return False
    if od[_TYP] == MARKET:
        od[_LAST] = i + 1                       # a market order is for the next bar's open only
        od[_DAY] = -1
    else:
        if eb is not None:
            od[_LAST] = i + eb
        # day-bound: intraday mode always; otherwise unless expiry_bars was given (then it may span days)
        od[_DAY] = TD[i + 1] if (intraday or eb is None) else -1
    od[_SIG] = i
    return True


def _bool_array(x, n, name):
    a = np.asarray(x)
    if a.shape != (n,):
        raise ValueError(f"{name}: expected one value per bar ({n}), got shape {a.shape}")
    if a.dtype.kind == "f":
        a = np.nan_to_num(a) != 0
    return a.astype(bool)


def _make_factory(side, d, tmpl, rules, n, TD, TE, intraday):
    """Normalise one side of a Signals object.  Returns (entry mask, mk, exit flags, trail values); mk(i) gives the
    order for a signal on bar i, None when a value is NaN (void) or False when it may not be placed (dropped)."""
    entry = _bool_array(d["entry"], n, "entry")
    base = tmpl[:]
    base[_SIDE] = side
    has = set()
    arrs = []
    for k, (idx, must_pos, is_int) in _ORDER_FIELDS.items():
        v = d.get(k)
        if v is None:
            continue
        has.add(k)
        if np.ndim(v) == 0:
            v = float(v)
            if v != v:
                raise ValueError(f"{k} is NaN")
            if must_pos and not v > 0:
                raise ValueError(f"{k} must be > 0")
            base[idx] = int(v) if is_int else v
        else:
            a = np.asarray(v, dtype="float64")
            if a.shape != (n,):
                raise ValueError(f"{k}: expected one value per bar ({n}), got shape {a.shape}")
            arrs.append((idx, a, must_pos, is_int))
    for k in ("be_trigger_r", "trail_r", "trail_trigger_r"):
        if getattr(rules, k) is not None:
            has.add(k)
    _check_structure(has, "long side" if side > 0 else "short side")
    order = d.get("order", "market")
    typ_arr = None
    if isinstance(order, str):
        base[_TYP] = _ORDER_CODES[order]
        needs_price = base[_TYP] != MARKET
    elif np.ndim(order) == 0:
        base[_TYP] = int(order)
        needs_price = base[_TYP] != MARKET
    else:
        typ_arr = np.asarray(order).astype("int64")
        if typ_arr.shape != (n,) or ((typ_arr < 0) | (typ_arr > 2)).any():
            raise ValueError("order array must hold MARKET / STOP / LIMIT codes, one per bar")
        needs_price = bool((typ_arr[entry] != MARKET).any())
    if base[_TYP] not in (MARKET, STOP, LIMIT):
        raise ValueError("order must be 'market', 'stop' or 'limit'")
    if needs_price and "price" not in has:
        raise ValueError("stop and limit orders need a price")
    eb_c, eb_a = None, None
    eb = d.get("expiry_bars")
    if eb is not None:
        if np.ndim(eb) == 0:
            eb_c = int(eb)
            if eb_c < 1:
                raise ValueError("expiry_bars must be >= 1")
        else:
            eb_a = np.asarray(eb, dtype="float64")
            if eb_a.shape != (n,):
                raise ValueError("expiry_bars: expected one value per bar")
    if d.get("expiry_time") is not None:
        base[_EXP_TMIN] = tmin_of(d["expiry_time"])

    def mk(i):
        od = base[:]
        if typ_arr is not None:
            od[_TYP] = int(typ_arr[i])
        is_market = od[_TYP] == MARKET
        for idx, a, must_pos, is_int in arrs:
            v = a[i]
            if idx == _PRICE and is_market:
                continue                    # a market order has no price: whatever is in the array is ignored
            if v != v or (must_pos and v <= 0):
                return None                 # NaN (or a non-positive distance) voids the signal
            od[idx] = int(v) if is_int else float(v)
        e_b = eb_c
        if not is_market:
            p = od[_PRICE]
            if p != p or p == _INF or p == -_INF:
                return None
            if eb_a is not None:
                v = eb_a[i]
                if v != v or v < 1:
                    return None
                e_b = int(v)
        if not _finish_order(od, i, e_b, TD, TE, intraday):
            return False                    # may not be carried into the next trading day ("dropped")
        return od

    ex = d.get("exit")
    ex = None if ex is None else _flags(_bool_array(ex, n, "exit"))
    tr = d.get("trail")
    if tr is not None:
        tr = np.asarray(tr, dtype="float64")
        if tr.shape != (n,):
            raise ValueError("trail: expected one value per bar")
        tr = _dbl(tr)
    return entry, mk, ex, tr


def _session_flags(bars, session):
    c = bars._flag_cache.get(session)
    if c is None:
        tmin = bars.tmin.astype("int64")
        te = bars.tmin_end.astype("int64")
        td = bars.tday_id
        n = bars.n
        multi = session.allow_multi_day
        hold = np.ones(n, dtype=bool) if multi else (te <= TMIN_FLAT)
        le = 9999 if session.last_entry is None else tmin_of(session.last_entry)
        fe = 0 if session.first_entry is None else tmin_of(session.first_entry)
        base = ~bars.incomplete & hold & (tmin >= fe)
        flat = None
        if not multi:
            nxt = np.zeros(n, dtype=bool)
            nxt[:-1] = hold[1:] & (td[1:] == td[:-1])
            flat = _flags(hold & ~nxt)
        c = {"mkt": _flags(base & (tmin <= le)), "rest": _flags(base & (te <= le)), "flat": flat}
        if len(bars._flag_cache) >= 16:
            bars._flag_cache.clear()
        bars._flag_cache[session] = c
    return c


def _time_exit_flags(bars, exit_time):
    x = TMIN_DAY_END if hm(exit_time) == MOD_DAY_END else tmin_of(exit_time)
    key = ("tx", x)
    c = bars._flag_cache.get(key)
    if c is None:
        e = bars.tmin_end.astype("int64") <= x
        td = bars.tday_id
        nxt = np.zeros(bars.n, dtype=bool)
        nxt[:-1] = e[1:] & (td[1:] == td[:-1])
        c = _flags(e & ~nxt)
        if len(bars._flag_cache) >= 16:
            bars._flag_cache.clear()
        bars._flag_cache[key] = c
    return c


def _simulate(bars, strategy, acts=None):
    """The state machine.  Returns (list of trade tuples, diagnostics dict).  If `acts` is a list, every bar on which
    a callback does something is appended to it as (bar, exit, new stop, new target, cancel, long order, short order);
    check_no_lookahead compares these."""
    session, rules = strategy.session, strategy.rules
    n = bars.n
    Ls = bars._lists()
    O, H, Lo, C, TD, TE = Ls["o"], Ls["h"], Ls["l"], Ls["c"], Ls["tday"], Ls["tmin_end"]
    fl = _session_flags(bars, session)
    MKT, RST, FLAT = fl["mkt"], fl["rest"], fl["flat"]
    TX = _time_exit_flags(bars, rules.exit_time) if rules.exit_time is not None else None
    max_tpd = None if session.max_trades_per_day is None else int(session.max_trades_per_day)
    intraday = not session.allow_multi_day
    SL, COST = SLIPPAGE, COST_RT
    nan = float("nan")
    tmpl = _order_template(rules)
    diag = {"orders": 0, "void": 0, "dropped": 0, "fills": 0, "conflicts": 0}
    trades = []

    is_cb = isinstance(strategy, Callback)
    LE = SE = XL = XS = TRL = TRS = mkL = mkS = None
    SIG = []
    ctx = on_bar = ACT = NXA = None
    if is_cb:
        ctx = Context(bars, tmpl, intraday)
        on_bar = strategy.on_bar
        if strategy.active is not None:
            act = _bool_array(strategy.active, n, "active")
            ACT = _flags(act)
            ai = np.flatnonzero(act)
            if len(ai):                             # NXA[j] = first active bar after j, or n
                k = np.searchsorted(ai, np.arange(n), side="right")
                NXA = _i64(np.where(k < len(ai), ai[np.minimum(k, len(ai) - 1)], n))
            else:
                NXA = _i64(np.full(n, n))
    else:
        any_sig = np.zeros(n, dtype=bool)
        if strategy.sides[1] is not None:
            m, mkL, XL, TRL = _make_factory(1, strategy.sides[1], tmpl, rules, n, TD, TE, intraday)
            LE = _flags(m)
            any_sig |= m
        if strategy.sides[-1] is not None:
            m, mkS, XS, TRS = _make_factory(-1, strategy.sides[-1], tmpl, rules, n, TD, TE, intraday)
            SE = _flags(m)
            any_sig |= m
        SIG = _i64(np.flatnonzero(any_sig))
    nsig = len(SIG)
    sp = 0

    # ---- position state ---------------------------------------------------------------------------------------
    pos = 0
    e = sig = -1
    typ0 = MARKET
    entry = slip_in = 0.0
    stop = stop0 = tgt = tgt0 = tp1 = tp1_stop = None
    tp1_done = tp1_move = False
    frac = 0.0
    risk = nan
    be_trig = trail_dist = None
    be_off = trail_trig = 0.0
    be_done = False
    mb_bar = _BIG
    best = worst = 0.0
    exit_open = False
    pl = ps = None                      # pending long / short entry orders
    day = -1                            # trading day of the day counters
    day_n = 0
    day_net = 0.0

    def _open(j, s, f, od):
        nonlocal pos, e, sig, typ0, entry, slip_in, stop, stop0, tgt, tgt0, tp1, tp1_stop, tp1_done, tp1_move, frac
        nonlocal risk, be_trig, be_off, be_done, trail_dist, trail_trig, mb_bar, best, worst, day_n
        ty = od[_TYP]
        if ty == STOP:                  # a stop entry pays one tick of slippage
            entry = f + s * SL
            slip_in = SL
        else:
            entry = f
            slip_in = 0.0
        pos = s; e = j; sig = od[_SIG]; typ0 = ty
        st = od[_STOP]
        if st is None and od[_STOP_PTS] is not None:
            st = entry - s * od[_STOP_PTS]
        if st == _INF or st == -_INF:   # +/-inf means "no stop on this trade"
            st = None
        stop = stop0 = st
        risk = nan
        if st is not None:
            r = (entry - st) * s
            if 0 < r < _INF:
                risk = r
        tg = od[_TGT]
        if tg is None:
            if od[_TGT_PTS] is not None:
                tg = entry + s * od[_TGT_PTS]
            elif od[_TGT_R] is not None and risk == risk:
                tg = entry + s * od[_TGT_R] * risk
        if tg == _INF or tg == -_INF:
            tg = None
        tgt = tgt0 = tg
        t1 = od[_TP1]
        if t1 is None:
            if od[_TP1_PTS] is not None:
                t1 = entry + s * od[_TP1_PTS]
            elif od[_TP1_R] is not None and risk == risk:
                t1 = entry + s * od[_TP1_R] * risk
        if t1 is not None and (t1 == _INF or t1 == -_INF or (tg is not None and (t1 - tg) * s >= 0)):
            t1 = None                   # a first target must lie before the final target
        tp1 = t1; tp1_done = False; tp1_move = False
        frac = od[_TP1_FRAC]; tp1_stop = od[_TP1_STOP]
        b = od[_BE_PTS]
        if b is None and od[_BE_R] is not None and risk == risk:
            b = od[_BE_R] * risk
        be_trig = b; be_off = od[_BE_OFF]; be_done = False
        dist = od[_TR_PTS]
        if dist is None and od[_TR_R] is not None and risk == risk:
            dist = od[_TR_R] * risk
        trail_dist = dist
        g = od[_TRG_PTS]
        if g is None and od[_TRG_R] is not None and risk == risk:
            g = od[_TRG_R] * risk
        trail_trig = 0.0 if g is None else g
        mb = od[_MAXB]
        mb_bar = _BIG if mb is None else j + mb - 1
        best = worst = entry
        day_n += 1
        diag["fills"] += 1

    def _close(j, px, reason, at_open=False):
        nonlocal pos, day_net, best, worst
        s = pos
        if reason == "stop":            # a protective stop pays one tick of slippage
            fill = px - s * SL
            so = SL
        else:
            fill = px
            so = 0.0
        if at_open:
            if s > 0:
                if px > best: best = px
                if px < worst: worst = px
            else:
                if px < best: best = px
                if px > worst: worst = px
        if tp1_done:
            rem = 1.0 - frac
            gross = s * ((fill - entry) * rem + (tp1 - entry) * frac)
            slip = slip_in + so * rem
        else:
            gross = s * (fill - entry)
            slip = slip_in + so
        trades.append((sig, e, j, s, typ0, entry, fill, reason, gross, slip, j - e + (0 if at_open else 1),
                       (entry - worst) * s, (best - entry) * s, stop0, risk, tgt0, tp1_done,
                       tp1 if tp1_done else nan, frac if tp1_done else 0.0, at_open))
        if TD[e] == day:
            day_net += gross - COST
        pos = 0

    j = 0
    while j < n:
        if pos == 0 and pl is None and ps is None:
            # ---- idle: nothing can happen inside this bar -------------------------------------------------------
            if is_cb:
                if ACT is not None and not ACT[j]:
                    j = NXA[j]
                    continue
            else:
                sp = bisect.bisect_left(SIG, j, sp)
                if sp >= nsig:
                    break
                j = SIG[sp]
        else:
            o = O[j]; h = H[j]; l = Lo[j]
            entered = False
            ref = o
            # ---- 1. signal exit at the open ---------------------------------------------------------------------
            if pos != 0 and exit_open:
                _close(j, o, "signal", True)
                exit_open = False
            # ---- 2. entry orders --------------------------------------------------------------------------------
            if pos == 0 and (pl is not None or ps is not None):
                td = TD[j]
                if td != day:
                    day = td; day_n = 0; day_net = 0.0
                if pl is not None and (j > pl[_LAST] or TE[j] > pl[_EXP_TMIN] or (pl[_DAY] >= 0 and td != pl[_DAY])):
                    pl = None
                if ps is not None and (j > ps[_LAST] or TE[j] > ps[_EXP_TMIN] or (ps[_DAY] >= 0 and td != ps[_DAY])):
                    ps = None
                if pl is not None or ps is not None:
                    capped = max_tpd is not None and day_n >= max_tpd
                    fL = fS = None
                    if pl is not None and not capped:
                        ty = pl[_TYP]
                        if ty == MARKET:
                            if MKT[j]:
                                fL = o
                        elif RST[j]:
                            p = pl[_PRICE]
                            if ty == STOP:
                                if h >= p:                  # trades at or through the stop price
                                    fL = p if p > o else o  # ... at the stop, or the open if it opens beyond it
                            elif l < p:                     # limit: must trade strictly through
                                fL = p if p < o else o      # ... at the limit, or the open if that is better
                    if ps is not None and not capped:
                        ty = ps[_TYP]
                        if ty == MARKET:
                            if MKT[j]:
                                fS = o
                        elif RST[j]:
                            p = ps[_PRICE]
                            if ty == STOP:
                                if l <= p:
                                    fS = p if p < o else o
                            elif h > p:
                                fS = p if p > o else o
                    if fL is not None and fS is not None:
                        # both sides could fill in this bar: the one nearer to the open is taken first
                        dL = abs(fL - o); dS = abs(fS - o)
                        if dL == 0.0 and dS == 0.0:
                            fL = fS = None                  # contradictory orders at the same open: no trade
                            pl = ps = None
                            diag["conflicts"] += 1
                        elif dL < dS:
                            fS = None
                        elif dS < dL:
                            fL = None
                        elif (C[j] - fL) <= (fS - C[j]):    # exact tie: take the side that is worse at this close
                            fS = None
                        else:
                            fL = None
                    if fL is not None:
                        _open(j, 1, fL, pl)
                        ref = fL; entered = True
                        pl = ps = None                      # the other side is cancelled
                    elif fS is not None:
                        _open(j, -1, fS, ps)
                        ref = fS; entered = True
                        pl = ps = None
                    else:
                        if pl is not None and pl[_TYP] == MARKET:
                            pl = None
                        if ps is not None and ps[_TYP] == MARKET:
                            ps = None
            # ---- 3. the position inside bar j -------------------------------------------------------------------
            if pos != 0:
                # `ref` is the price the bar is measured from: its open, or the entry price on the entry bar.
                # On the entry bar of a stop / limit entry only the adverse extreme is known to follow the fill.
                full = (not entered) or typ0 == MARKET
                if pos > 0:
                    if stop is not None and l <= stop:
                        px = stop if stop < ref else ref    # at the stop, or the open if the bar gaps beyond it
                        if not entered and o > best: best = o
                        if px < worst: worst = px
                        _close(j, px, "stop")
                    elif full:
                        if tp1 is not None and not tp1_done and h > tp1:
                            tp1_done = True; tp1_move = True
                            if tp1 > best: best = tp1
                        if tgt is not None and h > tgt:     # strictly through the target
                            if tgt > best: best = tgt
                            if l < worst: worst = l
                            _close(j, tgt, "target")
                        else:
                            if h > best: best = h
                            if l < worst: worst = l
                    else:
                        cj = C[j]
                        if cj > best: best = cj
                        if l < worst: worst = l
                else:
                    if stop is not None and h >= stop:
                        px = stop if stop > ref else ref
                        if not entered and o < best: best = o
                        if px > worst: worst = px
                        _close(j, px, "stop")
                    elif full:
                        if tp1 is not None and not tp1_done and l < tp1:
                            tp1_done = True; tp1_move = True
                            if tp1 < best: best = tp1
                        if tgt is not None and l < tgt:
                            if tgt < best: best = tgt
                            if h > worst: worst = h
                            _close(j, tgt, "target")
                        else:
                            if l < best: best = l
                            if h > worst: worst = h
                    else:
                        cj = C[j]
                        if cj < best: best = cj
                        if h > worst: worst = h
                # ---- 4. close of bar j --------------------------------------------------------------------------
                if pos != 0:
                    if TX is not None and TX[j]:
                        _close(j, C[j], "time")
                    elif j >= mb_bar:
                        _close(j, C[j], "bars")
                    elif FLAT is not None and FLAT[j]:
                        _close(j, C[j], "eod")
                    elif j == n - 1:
                        _close(j, C[j], "end_of_data")
                    else:
                        s = pos
                        if tp1_move:
                            tp1_move = False
                            if tp1_stop is not None:
                                ns = entry + s * tp1_stop
                                if stop is None or (ns - stop) * s > 0: stop = ns
                        fav = (best - entry) * s
                        if be_trig is not None and not be_done and fav >= be_trig:
                            be_done = True
                            ns = entry + s * be_off
                            if stop is None or (ns - stop) * s > 0: stop = ns
                        if trail_dist is not None and fav >= trail_trig:
                            ns = best - s * trail_dist
                            if stop is None or (ns - stop) * s > 0: stop = ns
                        if not is_cb:
                            TR = TRL if s > 0 else TRS
                            if TR is not None:
                                ns = TR[j]
                                if ns == ns and (stop is None or (ns - stop) * s > 0): stop = ns
                            X = XL if s > 0 else XS
                            if X is not None and X[j]:
                                exit_open = True
        # ---- new decisions at the close of bar j ----------------------------------------------------------------
        if is_cb:
            ctx.i = j
            ctx.position = pos
            if pos != 0:
                ctx.entry_price = entry; ctx.entry_bar = e; ctx.stop = stop; ctx.target = tgt
                ctx.bars_held = j - e + 1
                ctx.mfe = (best - entry) * pos; ctx.mae = (entry - worst) * pos
                ctx.open_pts = (C[j] - entry) * pos
                ctx.risk = risk
            elif ctx.entry_bar is not None:
                ctx.entry_price = ctx.entry_bar = ctx.stop = ctx.target = None
                ctx.bars_held = 0
                ctx.mfe = ctx.mae = ctx.open_pts = 0.0
                ctx.risk = nan
            ctx.exiting = exit_open
            ctx.pending_long = pl is not None
            ctx.pending_short = ps is not None
            if TD[j] == day:
                ctx.trades_today = day_n; ctx.net_today = day_net
            else:
                ctx.trades_today = 0; ctx.net_today = 0.0
            ctx.n_trades = len(trades)
            on_bar(ctx)
            if ctx._dirty:
                ctx._dirty = False
                if acts is not None:
                    acts.append((j, ctx._exit and pos != 0,
                                 "-" if (ctx._set_stop is _UNSET or pos == 0) else ctx._set_stop,
                                 "-" if (ctx._set_tgt is _UNSET or pos == 0) else ctx._set_tgt, ctx._cancel,
                                 None if ctx._ol is None else tuple(ctx._ol),
                                 None if ctx._os is None else tuple(ctx._os)))
                if ctx._void:
                    diag["void"] += ctx._void
                    ctx._void = 0
                if ctx._dropped:
                    diag["dropped"] += ctx._dropped
                    ctx._dropped = 0
                if ctx._exit:
                    ctx._exit = False
                    if pos != 0:
                        exit_open = True
                if ctx._set_stop is not _UNSET:
                    if pos != 0:
                        stop = ctx._set_stop
                    ctx._set_stop = _UNSET
                if ctx._set_tgt is not _UNSET:
                    if pos != 0:
                        tgt = ctx._set_tgt
                    ctx._set_tgt = _UNSET
                cz = ctx._cancel
                if cz:
                    ctx._cancel = 0
                    if cz & 1: pl = None
                    if cz & 2: ps = None
                ol, os_ = ctx._ol, ctx._os
                if ol is not None or os_ is not None:
                    ctx._ol = ctx._os = None
                    if pos != 0 and not exit_open:
                        raise RuntimeError(f"bar {j}: entry order while a position is open (call ctx.exit() to reverse)")
                    if ol is not None:
                        pl = ol; diag["orders"] += 1
                    if os_ is not None:
                        ps = os_; diag["orders"] += 1
        elif (pos == 0 or exit_open) and j + 1 < n:
            if LE is not None and LE[j]:
                od = mkL(j)
                if od is None:
                    diag["void"] += 1
                elif od is False:
                    diag["dropped"] += 1
                else:
                    pl = od; diag["orders"] += 1
            if SE is not None and SE[j]:
                od = mkS(j)
                if od is None:
                    diag["void"] += 1
                elif od is False:
                    diag["dropped"] += 1
                else:
                    ps = od; diag["orders"] += 1
        j += 1
    return trades, diag


# =====================================================================================================================
# 6. TRADES TABLE AND STATISTICS
# =====================================================================================================================
TRADE_COLUMNS = ["trade_id", "entry_time", "exit_time", "entry_day", "direction", "order_type", "entry_price",
                 "exit_price", "exit_reason", "gross_pts", "slippage_pts", "cost_pts", "net_pts", "bars_held",
                 "minutes_held", "mae_pts", "mfe_pts", "stop_price", "risk_pts", "r_multiple", "target_price",
                 "partial_exit", "partial_price", "partial_frac", "signal_bar", "entry_bar", "exit_bar", "split"]


@dataclass
class RunResult:
    """Result of run(): trades (DataFrame, one row per trade, see ENGINE.md), diag (counts: orders placed, fills,
    void = signals with a NaN value, dropped = signals on the last bar of a trading day that may not be carried into
    the next, conflicts = contradictory orders at one open), the session and trade rules used, the path ('arrays' or
    'callback'), tradeify_usable."""
    trades: pd.DataFrame
    diag: dict
    session: Session
    rules: TradeRules
    path: str
    resolution: int
    tradeify_usable: bool
    seconds: float


def _et_index(t):
    return pd.DatetimeIndex(np.asarray(t, dtype="int64").astype("datetime64[s]"), tz="UTC").tz_convert(NY)


def _trades_frame(bars, rows):
    cols = list(zip(*rows)) if rows else [()] * 20
    (sig, e, x, side, typ, entry, exitp, reason, gross, slip, held, mae, mfe, stop0, risk, tgt0, part, p_px, p_frac,
     at_open) = cols
    e = np.asarray(e, dtype="int64")
    x = np.asarray(x, dtype="int64")
    at_open = np.asarray(at_open, dtype=bool)
    t_in = bars.t[e]
    t_out = np.where(at_open, bars.t[x], bars.t_end[x])
    gross = np.asarray(gross, dtype="float64")
    net = gross - COST_RT
    risk = np.asarray(risk, dtype="float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        r_mult = net / risk
    entry_day = bars.tday[e]
    none_nan = lambda v: np.asarray([np.nan if q is None else q for q in v], dtype="float64")
    df = pd.DataFrame({
        "trade_id": np.arange(len(e), dtype="int64"),
        "entry_time": _et_index(t_in),           # ET; open of the bar in which the entry was filled
        "exit_time": _et_index(t_out),           # ET; end of the exit bar (its open for an exit at the open)
        "entry_day": pd.DatetimeIndex(entry_day.astype("datetime64[s]")),   # trading day of the entry
        "direction": np.asarray(side, dtype="int64"),
        "order_type": [_ORDER_NAMES[k] for k in typ],
        "entry_price": np.asarray(entry, dtype="float64"),
        "exit_price": np.asarray(exitp, dtype="float64"),
        "exit_reason": list(reason),
        "gross_pts": gross,
        "slippage_pts": np.asarray(slip, dtype="float64"),
        "cost_pts": np.full(len(e), COST_RT),
        "net_pts": net,
        "bars_held": np.asarray(held, dtype="int64"),
        "minutes_held": (t_out - t_in) / 60.0,
        "mae_pts": np.asarray(mae, dtype="float64"),
        "mfe_pts": np.asarray(mfe, dtype="float64"),
        "stop_price": none_nan(stop0),
        "risk_pts": risk,
        "r_multiple": r_mult,
        "target_price": none_nan(tgt0),
        "partial_exit": np.asarray(part, dtype=bool),
        "partial_price": np.asarray(p_px, dtype="float64"),
        "partial_frac": np.asarray(p_frac, dtype="float64"),
        "signal_bar": np.asarray(sig, dtype="int64"),
        "entry_bar": e,
        "exit_bar": x,
        "split": np.where(entry_day >= np.datetime64(SPLIT_DATE, "D"), "OOS", "IS").astype(object),
    })
    return df[TRADE_COLUMNS]


def run(bars, strategy):
    """Simulate a strategy (a Signals or a Callback object) on bars.  Returns a RunResult."""
    if not isinstance(strategy, (Signals, Callback)):
        raise TypeError("strategy must be an engine.Signals (path a) or engine.Callback (path b) object")
    t0 = time.perf_counter()
    rows, diag = _simulate(bars, strategy)
    trades = _trades_frame(bars, rows)
    return RunResult(trades=trades, diag=diag, session=strategy.session, rules=strategy.rules,
                     path="callback" if isinstance(strategy, Callback) else "arrays", resolution=bars.res,
                     tradeify_usable=not strategy.session.allow_multi_day, seconds=time.perf_counter() - t0)


def split_years():
    """Length of the fixed IS / OOS / ALL periods in calendar years (the same for every test)."""
    f = np.datetime64(DATA_FIRST_DAY, "D")
    s = np.datetime64(SPLIT_DATE, "D")
    last = np.datetime64(DATA_LAST_DAY, "D") + np.timedelta64(1, "D")
    d = lambda a, b: float((b - a).astype("int64")) / 365.25
    return {"IS": d(f, s), "OOS": d(s, last), "ALL": d(f, last)}


def _t_one_sided(x):
    """mean, sample std, t, one-sided p-value for mean > 0 (Student t, n-1 degrees of freedom)."""
    n = len(x)
    if n == 0:
        return None, None, None, None
    mean = float(np.mean(x))
    if n < 2:
        return mean, None, None, None
    sd = float(np.std(x, ddof=1))
    if not sd > 0:
        return mean, sd, None, None
    t = mean / (sd / math.sqrt(n))
    return mean, sd, float(t), float(_sps.t.sf(t, n - 1))


def bootstrap_mean_ci(x, n_boot=BOOT_RESAMPLES, seed=BOOT_SEED, level=0.95):
    """Seeded percentile bootstrap interval for the mean (resampling trades with replacement)."""
    x = np.asarray(x, dtype="float64")
    n = len(x)
    if n < 2:
        return None
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot)
    chunk = max(1, min(n_boot, 4_000_000 // n))
    k = 0
    while k < n_boot:
        m = min(chunk, n_boot - k)
        means[k:k + m] = x[rng.integers(0, n, size=(m, n))].mean(axis=1)
        k += m
    a = (1.0 - level) / 2.0
    lo, hi = np.percentile(means, [100 * a, 100 * (1 - a)])
    return [float(lo), float(hi)]


def _split_stats(df, years):
    n = len(df)
    net = df["net_pts"].to_numpy(dtype="float64")
    mean, sd, t, p = _t_one_sided(net)
    out = {"trades": int(n), "mean_net_pts": mean, "std_net_pts": sd, "t_stat": t, "p_one_sided": p,
           "boot_ci95_mean": bootstrap_mean_ci(net)}
    wins = net[net > 0].sum()
    losses = -net[net < 0].sum()
    out["win_rate"] = float((net > 0).mean()) if n else None
    out["profit_factor"] = float(wins / losses) if losses > 0 else None
    r = df["r_multiple"].to_numpy(dtype="float64")
    r = r[np.isfinite(r)]
    out["mean_r"] = float(r.mean()) if len(r) else None
    out["trades_with_stop"] = int(len(r))
    mae = df["mae_pts"].to_numpy(dtype="float64")
    out["mae_median_pts"] = float(np.median(mae)) if n else None
    out["mae_p90_pts"] = float(np.percentile(mae, 90)) if n else None
    out["median_minutes_held"] = float(np.median(df["minutes_held"].to_numpy(dtype="float64"))) if n else None
    out["trades_per_year"] = float(n / years)
    out["total_net_pts"] = float(net.sum())
    out["mean_gross_pts"] = float(df["gross_pts"].mean()) if n else None
    days = pd.DatetimeIndex(df["entry_day"])
    yr = np.asarray(days.year)
    out["net_pts_by_year"] = {str(int(y)): float(net[yr == y].sum()) for y in np.unique(yr)}
    out["trades_by_year"] = {str(int(y)): int((yr == y).sum()) for y in np.unique(yr)}
    # day-clustered test: several trades on one day are not independent, so test the mean of DAILY net points
    daily = pd.Series(net).groupby(np.asarray(days.values)).sum().to_numpy() if n else np.empty(0)
    dm, dsd, dt, dp = _t_one_sided(daily)
    out["days_traded"] = int(len(daily))
    out["day_mean_net_pts"] = dm
    out["day_std_net_pts"] = dsd
    out["day_t_stat"] = dt
    out["day_p_one_sided"] = dp
    out["worst_day_net_pts"] = float(daily.min()) if len(daily) else None
    if n:
        eq = np.cumsum(net)
        out["max_drawdown_pts"] = float(np.max(np.maximum.accumulate(np.maximum(eq, 0.0)) - eq))
    else:
        out["max_drawdown_pts"] = None
    return out


def stats(trades):
    """Statistics of a trades table with the FIXED split.  Returns {'split_date', 'IS', 'OOS', 'ALL', ...}; each split
    has: trades, mean_net_pts, std_net_pts, t_stat, p_one_sided (mean > 0, Student t), boot_ci95_mean (seeded, 2,000
    resamples), win_rate, profit_factor, mean_r and trades_with_stop, mae_median_pts, mae_p90_pts,
    median_minutes_held, trades_per_year, net_pts_by_year, trades_by_year, the day-clustered test (days_traded,
    day_mean_net_pts, day_std_net_pts, day_t_stat, day_p_one_sided), total_net_pts, mean_gross_pts, worst_day_net_pts,
    max_drawdown_pts.  A trade belongs to the split of its entry trading day.  None = not defined (too few trades,
    no losing trade, ...)."""
    yrs = split_years()
    sp = trades["split"].to_numpy()
    return {
        "split_date": SPLIT_DATE, "is_fraction": IS_FRACTION, "split_years": yrs,
        "bootstrap": {"resamples": BOOT_RESAMPLES, "seed": BOOT_SEED},
        "IS": _split_stats(trades[sp == "IS"], yrs["IS"]),
        "OOS": _split_stats(trades[sp == "OOS"], yrs["OOS"]),
        "ALL": _split_stats(trades, yrs["ALL"]),
    }


def format_stats(st):
    """A short text table of a stats() dict."""
    lines = [f"split date {st['split_date']} (IS before, OOS from)"]
    f = lambda v, fmt="{:.3f}": "n/a" if v is None else fmt.format(v)
    for k in ("IS", "OOS", "ALL"):
        s = st[k]
        ci = s["boot_ci95_mean"]
        lines.append(
            f"{k:>3}: n={s['trades']:<6} mean={f(s['mean_net_pts'])} sd={f(s['std_net_pts'])} t={f(s['t_stat'], '{:.2f}')} "
            f"p={f(s['p_one_sided'], '{:.4f}')} ci95=[{f(ci[0]) if ci else 'n/a'}, {f(ci[1]) if ci else 'n/a'}] "
            f"win={f(s['win_rate'], '{:.1%}')} pf={f(s['profit_factor'], '{:.2f}')} meanR={f(s['mean_r'])} "
            f"day_t={f(s['day_t_stat'], '{:.2f}')} trades/yr={f(s['trades_per_year'], '{:.1f}')} "
            f"total={f(s['total_net_pts'], '{:.1f}')}")
    return "\n".join(lines)


# =====================================================================================================================
# 7. RUNNER, NO-LOOKAHEAD CHECK, SELF-CHECK
# =====================================================================================================================
def _jsonable(x):
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (np.bool_, bool)):
        return bool(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        x = float(x)
        return x if math.isfinite(x) else None
    if isinstance(x, np.ndarray):
        return _jsonable(x.tolist())
    if x is None or isinstance(x, (int, str)):
        return x
    return str(x)


def _write_file(path, text, overwrite):
    """Write atomically.  Without overwrite an existing file is never replaced (FileExistsError)."""
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", newline="") as f:
        f.write(text)
    try:
        if overwrite:
            os.replace(tmp, path)
        else:
            try:
                os.link(tmp, path)      # fails if `path` exists, even if another process created it just now
            except FileExistsError:
                raise
            except OSError:             # a file system without hard links: exclusive create instead
                with open(path, "x", newline="") as f:
                    f.write(text)
            os.unlink(tmp)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class LookaheadError(AssertionError):
    """Raised by run_config when check_no_lookahead finds that a strategy's past decisions depend on later bars."""


_CLOSED_COLS = ["signal_bar", "entry_bar", "exit_bar", "direction", "order_type", "entry_price", "exit_price",
                "exit_reason", "net_pts", "mae_pts", "mfe_pts"]
_ENTRY_COLS = ["signal_bar", "entry_bar", "direction", "order_type", "entry_price", "stop_price", "target_price"]


def _same(a, b):
    """Element-wise equality of two columns / arrays; floats with a 1e-9 tolerance, NaN equal to NaN."""
    a, b = np.asarray(a), np.asarray(b)
    if a.shape != b.shape:
        return np.zeros(max(a.shape[0] if a.ndim else 1, 1), dtype=bool)
    if a.dtype.kind == "f" or b.dtype.kind == "f":
        a, b = a.astype("float64"), b.astype("float64")
        with np.errstate(invalid="ignore"):
            return (np.abs(a - b) <= 1e-9 + 1e-12 * np.abs(b)) | (np.isnan(a) & np.isnan(b)) | (a == b)
    return a == b


def _compare_frames(a, b, cols, what, k):
    if len(a) != len(b):
        return [f"cut {k}: {len(a)} {what} on the longer data, {len(b)} on the data truncated at bar {k}"]
    for c in cols:
        ok = _same(a[c].to_numpy(), b[c].to_numpy())
        if not ok.all():
            i = int(np.flatnonzero(~ok)[0])
            return [f"cut {k}: {what}: row {i} column {c!r} is {a[c].iloc[i]!r} on the longer data but "
                    f"{b[c].iloc[i]!r} on the data truncated at bar {k}"]
    return []


def _compare_signal_arrays(ref, st, k):
    """Per-bar arrays of two Signals objects must agree on bars < k (ref was built on more bars than st)."""
    out = []
    if ref.rules != st.rules or ref.session != st.session:
        out.append(f"cut {k}: trade rules or session rules depend on the amount of data")
    for s, name in ((1, "long"), (-1, "short")):
        da, db = ref.sides[s], st.sides[s]
        if (da is None) != (db is None):
            out.append(f"cut {k}: the {name} side exists only on one of the two runs")
            continue
        if da is None:
            continue
        for key in sorted(set(da) | set(db)):
            va, vb = da.get(key), db.get(key)
            if va is None and vb is None:
                continue
            if va is None or vb is None or (np.ndim(va) == 0) != (np.ndim(vb) == 0):
                out.append(f"cut {k}: {name}.{key} is given on only one of the two runs")
            elif np.ndim(va) == 0:
                if va != vb:
                    out.append(f"cut {k}: {name}.{key} is {va!r} on the longer data but {vb!r} on truncated data")
            else:
                va, vb = np.asarray(va)[:k], np.asarray(vb)
                ok = _same(va, vb)
                if not ok.all():
                    i = int(np.flatnonzero(~ok)[0]) if len(va) == len(vb) else -1
                    out.append(f"cut {k}: {name}.{key} at bar {i} is {va[i] if i >= 0 else '?'} on the longer data but "
                               f"{vb[i] if i >= 0 else '?'} on the data truncated at bar {k}: the value depends on "
                               f"later bars")
    return out


def _signal_cuts(ref, acts, n, n_cuts, rng):
    """Extra cuts for check_no_lookahead, placed where the strategy acts.  A value that looks ONE bar ahead through a
    clipped or wrapped index (np.roll(x, -1), shift(-1), x[min(i + 1, n - 1)]) differs between the full and the
    truncated data only on the last bar before the cut, so a random cut finds it only if that bar happens to carry a
    signal - almost never for a strategy with a few signals a day.  Path (a): cuts right after bars that carry an
    entry or exit signal.  Path (b): cuts right after bars on which the callback did something."""
    if isinstance(ref, Signals):
        m = np.zeros(n, dtype=bool)
        for d in ref.sides.values():
            for key in ("entry", "exit"):
                v = None if d is None else d.get(key)
                if v is not None and np.shape(v) == (n,):
                    m |= _bool_array(v, n, key)
        k = np.flatnonzero(m) + 1
    else:
        k = np.asarray([a[0] for a in acts], dtype="int64") + 1
    k = np.unique(k[(k >= n // 2) & (k < n)])
    if len(k) > n_cuts:
        k = rng.choice(k, size=n_cuts, replace=False)
    return sorted(int(x) for x in k)


def _same_action(a, b):
    """Two records of the callback log (or parts of them): equal up to the float tolerance of _same."""
    if isinstance(a, tuple) or isinstance(b, tuple):
        return (isinstance(a, tuple) and isinstance(b, tuple) and len(a) == len(b)
                and all(_same_action(x, y) for x, y in zip(a, b)))
    if a is None or b is None or isinstance(a, str) or isinstance(b, str):
        return a is b or (isinstance(a, str) and isinstance(b, str) and a == b)
    a, b = float(a), float(b)
    return a == b or (a != a and b != b) or abs(a - b) <= 1e-9 + 1e-12 * abs(b)


def _callback_actions_problems(strategy_fn, params, base, acts, k):
    """Path (b): the strategy is run on the first k bars followed by ONE more bar that holds nothing new (bar k at
    its real time, with the prices of bar k-1).  Everything the callback did up to bar k-1 - orders with all their
    values, exits, stop and target changes, cancels - must be the same as on the full data.  Unlike plain truncation
    the bar after the decision still exists, so this also finds a callback (or an array it reads) that is exactly one
    bar ahead."""
    tb = base.truncate(k + 1)
    o, h, l, c = tb.o.copy(), tb.h.copy(), tb.l.copy(), tb.c.copy()
    o[k], h[k], l[k], c[k] = o[k - 1], h[k - 1], l[k - 1], c[k - 1]
    tb = Bars(tb.t, o, h, l, c, tb.res, tmin_end=tb.tmin_end, incomplete=tb.incomplete, rth_counts=tb._rth_counts,
              source=tb.source)
    got = []
    try:
        _simulate(tb, strategy_fn(tb, params), got)
    except Exception as exc:
        return [f"cut {k}: the strategy failed when the bars from {k} on are unknown ({type(exc).__name__}: {exc})"]
    want = [a for a in acts if a[0] < k]
    got = [a for a in got if a[0] < k]
    for a, b in zip(want, got):
        if not _same_action(a, b):
            return [f"cut {k}: what the callback does on bar {min(a[0], b[0])} changes when the bars from {k} on are "
                    f"unknown: it uses bars that have not closed yet"]
    if len(want) != len(got):
        j = (want if len(want) > len(got) else got)[min(len(want), len(got))][0]
        return [f"cut {k}: what the callback does on bar {j} changes when the bars from {k} on are unknown: it uses "
                f"bars that have not closed yet"]
    return []


def check_no_lookahead(strategy_fn, params, bars, cuts=None, n_cuts=12, max_days=500, seed=0):
    """Does strategy_fn(bars, params) only use closed bars?  The strategy is run on the data and on the same data
    truncated at each cut k; a strategy without lookahead must then give
      - for path (a): identical signal arrays on all bars before k,
      - identical trades for every trade that closed before k,
      - identical entries (signal bar, entry bar, direction, entry price, stop, target) for every trade entered
        before k,
    and must not fail on the shorter data.  With cuts=None, n_cuts random cuts are placed in the second half of the
    first max_days trading days, plus up to n_cuts cuts where the strategy acts: for path (a) right after bars with
    an entry or exit signal; for path (b) right after bars on which the callback did something, where its actions
    are compared with the bars from the cut on made unknown (see _callback_actions_problems).  These find a value
    that is exactly one bar ahead, which a random cut almost never does.  About one to three seconds in all.  Pass
    explicit cuts to test on all of `bars` by plain truncation at those cuts only.
    Returns a list of problems (empty = passed).  The check samples: it is a safety net, not a proof."""
    auto = cuts is None
    if auto:
        base = bars
        if max_days is not None and len(bars.days) > max_days:
            base = bars.truncate(int(bars.days["first"].iloc[max_days]))
        rng = np.random.default_rng(seed)
        cuts = sorted({int(k) for k in rng.integers(base.n // 2, base.n - 1, size=n_cuts)})
    else:
        base = bars
        cuts = sorted(int(k) for k in cuts)
    acts = []
    try:
        ref = strategy_fn(base, params)
        if isinstance(ref, Callback):
            full = _trades_frame(base, _simulate(base, ref, acts)[0])
        else:
            full = run(base, ref).trades
    except Exception as exc:
        return [f"the strategy failed on {base.n} bars ({type(exc).__name__}: {exc})"]
    act_cuts = []
    if auto:
        extra = _signal_cuts(ref, acts, base.n, n_cuts, rng)
        if isinstance(ref, Callback):
            act_cuts = extra
        else:
            cuts = sorted(set(cuts) | set(extra))
    problems = []
    for k in cuts:
        tb = base.truncate(k)
        try:
            st = strategy_fn(tb, params)
            if isinstance(ref, Signals) and isinstance(st, Signals):
                found = _compare_signal_arrays(ref, st, k)
                if found:
                    problems += found
                    continue
            part = run(tb, st).trades
        except Exception as exc:        # e.g. an IndexError from reading bar i+1
            problems.append(f"cut {k}: the strategy failed on the data truncated at bar {k} "
                            f"({type(exc).__name__}: {exc})")
            continue
        found = _compare_frames(full[full["exit_bar"] < k - 1], part[part["exit_bar"] < k - 1], _CLOSED_COLS,
                                "trades closed before the cut", k)
        if not found:
            found = _compare_frames(full[full["entry_bar"] < k], part[part["entry_bar"] < k], _ENTRY_COLS,
                                    "trades entered before the cut", k)
        problems += found
    for k in act_cuts:
        problems += _callback_actions_problems(strategy_fn, params, base, acts, k)
    return problems


def run_config(config_id, family, params, strategy_fn, resolution, *, overwrite=False, out_dir=None, bars=None,
               check_lookahead=True, notes=None, verbose=True):
    """Run one configuration and write its two output files.

      config_id     unique id; becomes the file name (letters, digits, '.', '_', '-')
      family        name of the strategy family (free text)
      params        dict of the parameters (stored in the JSON; must be JSON-friendly)
      strategy_fn   strategy_fn(bars, params) -> engine.Signals (path a) or engine.Callback (path b)
      resolution    bar length in minutes (5 -> NSX_5m.npz, 1 -> NSX_1m.npz, anything else is resampled from 1-minute)
      overwrite     False (default): raise FileExistsError if an output file exists.  True: replace both.
      check_lookahead  True (default): first run check_no_lookahead on the first 500 trading days and raise
                    LookaheadError (writing nothing) if the strategy uses later bars.  False skips it (recorded as
                    "skipped" in the JSON) - fine for further parameter sets of a strategy function already checked.

    Writes  <out>/results/<config_id>.json  (stats, parameters, data file, engine version, session rules, diagnostics)
    and     <out>/trades/<config_id>.csv    (the trades table);  <out> defaults to research3/out.  Returns the JSON
    content as a dict.
    """
    if not isinstance(config_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", config_id):
        raise ValueError("config_id must be 1-200 characters of letters, digits, '.', '_' or '-'")
    out_dir = OUT_DIR if out_dir is None else out_dir
    res_dir = os.path.join(out_dir, "results")
    trd_dir = os.path.join(out_dir, "trades")
    os.makedirs(res_dir, exist_ok=True)
    os.makedirs(trd_dir, exist_ok=True)
    json_path = os.path.join(res_dir, config_id + ".json")
    csv_path = os.path.join(trd_dir, config_id + ".csv")
    if not overwrite:
        for p in (json_path, csv_path):
            if os.path.exists(p):
                raise FileExistsError(f"{p} exists; pass overwrite=True to replace it")
    t0 = time.perf_counter()
    if bars is None:
        bars = load_bars(resolution)
    elif bars.res != int(resolution):
        raise ValueError("bars.res does not match resolution")
    look = "skipped"
    if check_lookahead:
        problems = check_no_lookahead(strategy_fn, params, bars)
        if problems:
            raise LookaheadError(f"[{config_id}] lookahead check failed ({len(problems)} problem(s)); first: "
                                 + problems[0])
        look = "passed"
    strat = strategy_fn(bars, params)
    result = run(bars, strat)
    st = stats(result.trades)
    payload = _jsonable({
        "config_id": config_id, "family": family, "params": params, "resolution_min": bars.res,
        "data_file": bars.source, "incomplete_days_from": FILE_1M,
        "engine_version": ENGINE_VERSION, "engine_sha256": ENGINE_SHA256,
        "path": result.path, "session": asdict(result.session), "trade_rules": asdict(result.rules),
        "tradeify_usable": result.tradeify_usable,
        "costs": {"tick": TICK, "stop_order_slippage_pts": SLIPPAGE, "round_trip_cost_pts": COST_RT},
        "split_date": SPLIT_DATE, "n_bars": bars.n, "n_trades": len(result.trades), "diagnostics": result.diag,
        "lookahead_check": look, "notes": notes, "stats": st,
        "trades_file": csv_path, "seconds": round(time.perf_counter() - t0, 3),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    _write_file(csv_path, result.trades.to_csv(index=False, float_format="%.6f"), overwrite)
    _write_file(json_path, json.dumps(payload, indent=1, allow_nan=False), overwrite)
    if verbose:
        s_is, s_oos = st["IS"], st["OOS"]
        f = lambda v: "n/a" if v is None else f"{v:.3f}"
        print(f"[{config_id}] {family}: trades IS {s_is['trades']} OOS {s_oos['trades']} | mean net IS "
              f"{f(s_is['mean_net_pts'])} OOS {f(s_oos['mean_net_pts'])} | t IS {f(s_is['t_stat'])} OOS "
              f"{f(s_oos['t_stat'])} | {payload['seconds']}s")
    return payload


def _demo_orb(bars, params):
    """Demo for the timing check: two-sided opening-range breakout through path (a)."""
    orh, orl = opening_range(bars, "09:30", params.get("or_min", 30))
    go = (bars.tmin_end == TMIN_RTH_OPEN + params.get("or_min", 30)) & ~np.isnan(orh)
    return Signals(long=dict(entry=go, order="stop", price=orh, stop=orl),
                   short=dict(entry=go, order="stop", price=orl, stop=orh),
                   target_r=params.get("target_r", 2.0), exit_time="15:55", last_entry="12:00", max_trades_per_day=1)


def _demo_sma(bars, params):
    """Demo for the timing check: always-on moving-average cross with market orders through path (a) (dense)."""
    f, s = sma(bars.c, params.get("fast", 20)), sma(bars.c, params.get("slow", 50))
    up, dn = cross_above(f, s), cross_below(f, s)
    return Signals(np.where(up, 1, np.where(dn, -1, 0)), stop_pts=atr(bars.h, bars.l, bars.c, 14) * 3.0,
                   exit_long=dn, exit_short=up)


def main(argv=None):
    print(f"{ENGINE_VERSION}  sha256 {ENGINE_SHA256[:16] if ENGINE_SHA256 else 'n/a'}")
    print(f"fixed split: IS before {SPLIT_DATE}, OOS from {SPLIT_DATE} "
          f"({N_IS_DAYS} + {N_OOS_DAYS} = {N_COMPLETE_DAYS} complete regular-session days, "
          f"{DATA_FIRST_DAY} .. {DATA_LAST_DAY})")
    sp = compute_split()
    ok = (sp["split_date"] == SPLIT_DATE and sp["n_complete_days"] == N_COMPLETE_DAYS and sp["n_is_days"] == N_IS_DAYS
          and sp["first_day"] == DATA_FIRST_DAY and sp["last_day"] == DATA_LAST_DAY)
    print("split recomputed from NSX_1m.npz:", sp, "-> matches the constants" if ok else "-> MISMATCH")
    t0 = time.perf_counter()
    bars = load_bars(5)
    t_load = time.perf_counter() - t0
    print(bars, f"loaded in {t_load:.2f}s")
    for name, fn in (("opening-range breakout (sparse)", _demo_orb), ("SMA 20/50 cross (dense)", _demo_sma)):
        t0 = time.perf_counter()
        strat = fn(bars, {})
        t1 = time.perf_counter()
        res = run(bars, strat)
        t2 = time.perf_counter()
        st = stats(res.trades)
        t3 = time.perf_counter()
        print(f"\n{name}: signals {t1 - t0:.2f}s + simulation {t2 - t1:.2f}s + stats {t3 - t2:.2f}s = {t3 - t0:.2f}s "
              f"({len(res.trades)} trades, {bars.n} five-minute bars); with the load: {t3 - t0 + t_load:.2f}s")
        print(format_stats(st))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
