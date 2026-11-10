# ENGINE.md - the shared backtest engine (research3)

`engine.py` is the one engine every strategy test uses, so that fills, costs, session rules and statistics are the
same everywhere. `test_engine.py` holds its unit tests. Python 3.13 with numpy, pandas and scipy; run everything with
`python3 -I`.

## 0. The rule

**Family modules must not change the engine.** Import `engine.py` and use it as it is. Do not edit it, do not copy
parts of it into your module, do not overwrite its constants or functions at run time, and do not write your own
fills, costs, session logic, split or statistics. If something is missing or looks wrong, report it instead of
working around it. Every result file records `engine_version` and the SHA-256 of `engine.py`, so results made with a
changed engine can be found. Never write into `research3/data`.

## 1. Quick start

```python
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I ignores the current folder
import numpy as np
import engine as eng

def my_strategy(bars, params):          # must be a pure function of (bars, params): it is called more than once
    ...
    return eng.Signals(...)             # path (a), or eng.Callback(...) for path (b)

res = eng.run_config("myfam_001", "my_family", {"n": 20}, my_strategy, resolution=5)
print(eng.format_stats(res["stats"]))
```

A module outside `research3/code` inserts the absolute path of that folder instead. `python3 -I engine.py` prints the
engine version, the split date and a timing check. `python3 -I test_engine.py` runs the tests.

| You want to                      | Call                                                            |
|----------------------------------|-----------------------------------------------------------------|
| load bars                        | `eng.load_bars(5)` (cached per process)                         |
| try a strategy without files     | `r = eng.run(bars, strategy)`; `r.trades`, `eng.stats(r.trades)` |
| run a configuration for the record | `eng.run_config(config_id, family, params, strategy_fn, resolution)` |
| check a strategy for lookahead   | `eng.check_no_lookahead(strategy_fn, params, bars)` (empty list = passed) |

## 2. Bars

`bars = eng.load_bars(res)`: `res=5` reads `NSX_5m.npz`, `res=1` reads `NSX_1m.npz`, any other number of minutes is
resampled from the 1-minute bars with buckets aligned to the New York clock (`eng.load_bars(60, anchor="09:30")`
shifts the buckets so that one starts at 09:30). Bars that open at or after 16:15 ET (and before 18:00 ET) are dropped
in every year; no such bar is ever used. A bucket never crosses the 16:15-18:00 break (the evening part is its own
bar from 18:00). For a resolution that does not divide a day (7, 50, 65, 130, 195, 390, ...) the grid starts again at
midnight, so the last evening bar ends at 00:00 and the next one starts at 00:00; `eng.load_bars(65, anchor="09:30")`
gives six bars per regular session. All arrays are read-only numpy arrays of length `bars.n`.

| Field | Meaning |
|---|---|
| `t`, `t_end` | bar open time and nominal bar end, epoch seconds UTC |
| `o h l c`, `res` | prices in index points; bar length in minutes |
| `date`, `mod`, `wd` | New York calendar date, minute of day at the bar open (09:30 = 570), weekday (Mon = 0) |
| `end_mod` | New York minute of day at the nominal bar end |
| `tday`, `tday_id`, `tday_wd` | trading-day date (a trading day runs 18:00 ET of the previous evening to 16:15 ET), the same as an integer, its weekday. Sunday 18:00 belongs to Monday |
| `tmin`, `tmin_end` | minutes since the 18:00 start of the trading day at the bar open / nominal end (18:00 = 0, 09:30 = 930, 16:00 = 1320, 16:15 = 1335). Use these to compare times across midnight; `eng.tmin_of("09:30")` converts a clock time |
| `rth` | True when the bar lies inside the regular session 09:30-16:00 ET |
| `incomplete` | True when the bar's trading day has fewer than 370 regular-session 1-minute bars. Always counted in `NSX_1m.npz`, for every resolution. Covers the whole trading day, also its evening session |
| `day_idx`, `days` | row of the bar's trading day in `bars.days`; `days` is a DataFrame with one row per trading day: `date, tday_id, first, last, rth_first, rth_last, rth_open, rth_high, rth_low, rth_close, rth_first_mod, n_rth_1m, complete, oos` |
| `et` | bar open times as a tz-aware pandas index in New York time (built on first use) |

Helpers: `bars.time_between("09:30", "11:00")` (bar OPEN time in [start, end)), `bars.opens_at("09:30")`,
`bars.ends_at("10:00")` (the bar that closes at 10:00), `bars.frame(i0, i1)` (a few bars as a table),
`bars.truncate(k)` (the first k bars), `eng.hm("09:30")` (minute of day).

All time handling goes through the tz database, so the regular session is 09:30-16:00 ET in every week of the year,
including the weeks of the daylight-saving changes.

`bars.days` holds the whole day, also for the day in progress: do not read the current day's row inside a signal
(that is lookahead). Use `eng.lag_days_to_bars(bars, per_day_values)` to bring day-level values to the bars with a
one-day lag.

## 3. Indicator helpers

All are vectorized and have no lookahead: the value at bar i uses bars <= i only. NaN until enough history exists.

Series helpers (plain arrays in, arrays out):

| Function | Returns |
|---|---|
| `sma(x, n)`, `ema(x, n)`, `wilder(x, n)` | simple, exponential (alpha 2/(n+1), seeded with the first value) and Wilder averages |
| `true_range(h, l, c)`, `atr(h, l, c, n=14)` | true range; Wilder ATR |
| `rsi(c, n=14)` | Wilder RSI |
| `adx(h, l, c, n=14)` | `(adx, plus_di, minus_di)`, Wilder |
| `rolling_std(x, n, ddof=0)`, `bollinger(x, n=20, k=2.0)` | standard deviation; `(mid, upper, lower)` |
| `keltner(h, l, c, n=20, atr_n=10, mult=2.0)` | `(mid, upper, lower)`: EMA and EMA +/- mult x ATR |
| `donchian(h, l, n, include_current=True)` | `(highest high, lowest low)` of n bars; `include_current=False` uses the n bars before the current one |
| `rolling_max(x, n)`, `rolling_min(x, n)` | rolling highs / lows including the current bar |
| `lag(x, k)` | x shifted k >= 0 bars into the past |
| `cross_above(a, b)`, `cross_below(a, b)` | True on the bar of the cross |
| `masked(mask, fn, *arrays, ffill=False)` | run `fn` on the bars where mask is True only (for example `masked(bars.rth, lambda h, l, c: eng.atr(h, l, c, 14), bars.h, bars.l, bars.c)` for an ATR of regular-session bars) |

Session helpers (take `bars`):

| Function | Returns |
|---|---|
| `prior_rth(bars, require_complete=True)` | dict `open, high, low, close` of the prior regular session, constant over the trading day |
| `overnight_range(bars)` | `(high, low)` of 18:00-09:30 ET: running while the overnight session is in progress, fixed from 09:30 |
| `opening_range(bars, start="09:30", minutes=30, require_full=True)` | `(high, low)` of the window, from the bar that completes it to the end of the trading day |
| `rth_open(bars, max_late_min=5)` | open of the regular session, from its first bar on |
| `gap(bars, pct=False)` | regular-session open minus prior regular-session close |
| `floor_pivots(bars)` | dict `P, R1, R2, R3, S1, S2, S3` from the prior regular session |
| `camarilla_pivots(bars)` | dict `R1..R4, S1..S4` from the prior regular session |
| `daily_atr(bars, n=14, method="wilder")` | ATR of complete regular sessions, as of the last complete session before the bar's trading day |
| `session_high_low(bars, start="09:30")` | running `(high, low)` since `start`, including the current bar |
| `twap_vwap_proxy(bars, anchor="09:30", bands=False)` | TIME-weighted average of typical price since the anchor. A VWAP proxy only: the data has no volume, so this is not a true VWAP. `bands=True` adds the running standard deviation |
| `lag_days_to_bars(bars, per_day, valid=None)` | a per-day array spread over the bars with a one-day lag |

Notes: (0) `ema` and `wilder`, and `atr`, `rsi`, `adx`, `keltner` which are built on them, are recursive: leading
NaNs are skipped, but one NaN after the first valid value makes every later value NaN. Give them price series, not a
level helper that is NaN for part of each day (gap, opening range, prior-session levels); `sma`, `rolling_*` and
`bollinger` recover once the NaN has left the window; (1) levels from the prior regular session are NaN on the day
after an incomplete session (holiday half days, source gaps) unless `require_complete=False`; (2) the regular session of a resolution is made of the bars that lie
fully inside 09:30-16:00, so session levels are exact for resolutions that divide 30 minutes (1, 2, 3, 5, 6, 10, 15,
30) and approximate otherwise; (3) `atr`, `rsi`, `adx`, moving averages run over all bars, including the overnight
session and the break; use `masked` for regular-session-only versions.

## 4. Path (a): precomputed arrays - worked example

The strategy returns `eng.Signals`. A value on bar i is decided at the close of bar i and acts from bar i+1. This is
the fast path (16 years of 5-minute bars in about one second).

<!-- example: path-a -->
```python
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import engine as eng


def orb(bars, p):
    """Opening-range breakout.  When the first p['or_min'] minutes of the regular session are complete: a buy stop
    one tick above the range high and a sell stop one tick below the range low (whichever fills first cancels the
    other), protective stop at the other side of the range, target at p['target_r'] times the risk, no fill after
    p['last_entry'], out at p['exit_time'], one trade per day.  Ranges wider than p['max_width_atr'] daily ATRs are
    skipped."""
    orh, orl = eng.opening_range(bars, "09:30", p["or_min"])
    go = (bars.tmin_end == eng.tmin_of("09:30") + p["or_min"]) & ~np.isnan(orh)   # the bar that completes the range
    go &= (orh - orl) <= p["max_width_atr"] * eng.daily_atr(bars, 14)
    return eng.Signals(
        long=dict(entry=go, order="stop", price=orh + eng.TICK, stop=orl),
        short=dict(entry=go, order="stop", price=orl - eng.TICK, stop=orh),
        target_r=p["target_r"], last_entry=p["last_entry"], exit_time=p["exit_time"], max_trades_per_day=1)


params = {"or_min": 30, "target_r": 2.0, "max_width_atr": 0.5, "last_entry": "12:00", "exit_time": "15:55"}
res = eng.run_config("example_orb_or30_r2", "example_opening_range_breakout", params, orb, resolution=5)
print(eng.format_stats(res["stats"]))
```

`Signals` in short (full list in section 8):

- Simple form: `eng.Signals(direction, order="market", price=..., stop=..., target=..., ...)` with `direction` +1 /
  -1 / 0 per bar and the other values as scalars or per-bar arrays (read at the signal bar).
- Two-sided form: `eng.Signals(long=dict(entry=mask, ...), short=dict(entry=mask, ...), ...)`; both orders may wait
  at once and the first to fill cancels the other.
- Exit signals: `exit_long` / `exit_short` bool arrays close the position at the next bar's open. An entry signal on
  the same bar as an exit signal is taken (reverse at the same open). Other entry signals that arrive while a
  position is open are ignored.

## 5. Path (b): per-bar callback - worked example

For logic that depends on the trade's own path. The strategy returns `eng.Callback(on_bar, ...)`; the engine calls
`on_bar(ctx)` after every closed bar. The fills are the same code as in path (a).

<!-- example: path-b -->
```python
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import engine as eng


def trend_pullback(bars, p):
    """Buy a pullback to the fast EMA in an up-trend with a stop order above the pullback bar.  Path-dependent
    parts: after the trade is one R in profit a chandelier stop trails from the highest high since entry; a close
    below the slow EMA exits at the next open; no new trade once the day's closed trades have lost
    p['daily_stop_pts'] points."""
    a = eng.atr(bars.h, bars.l, bars.c, 14)
    fast, slow = eng.ema(bars.c, p["fast"]), eng.ema(bars.c, p["slow"])
    h, l, c = bars.h, bars.l, bars.c
    window = bars.time_between("09:45", "15:00")

    def on_bar(ctx):
        i = ctx.i                                    # the bar that just closed; never read an array beyond i
        if ctx.position == 0:
            if ctx.pending_long or not window[i] or ctx.net_today <= -p["daily_stop_pts"]:
                return
            if fast[i] > slow[i] and l[i] <= fast[i] < c[i]:
                ctx.buy_stop(h[i] + eng.TICK, stop=l[i] - 0.5 * a[i], expiry_bars=2)
        elif c[i] < slow[i]:
            ctx.exit()                               # out at the next bar's open
        elif ctx.mfe >= ctx.risk:
            new_stop = h[ctx.entry_bar:i + 1].max() - p["trail_atr"] * a[i]
            if new_stop > ctx.stop:
                ctx.set_stop(new_stop)               # counts from the next bar

    return eng.Callback(on_bar, active=window, exit_time="15:55", max_trades_per_day=p["max_trades"])


params = {"fast": 20, "slow": 100, "trail_atr": 3.0, "daily_stop_pts": 60.0, "max_trades": 3}
res = eng.run_config("example_pullback_20_100", "example_trend_pullback", params, trend_pullback, resolution=5)
print(eng.format_stats(res["stats"]))
```

`ctx` in short:

- State: `i`, `bars`, `position` (+1 / -1 / 0), `entry_price`, `entry_bar`, `stop`, `target`, `risk`, `bars_held`,
  `mfe`, `mae`, `open_pts`, `exiting`, `pending_long`, `pending_short`, `trades_today`, `net_today`, `n_trades`, and a
  dict `user` for the strategy's own state.
- Actions (all count from the next bar): `buy_market(**kw)`, `sell_market(**kw)`, `buy_stop(price, **kw)`,
  `sell_stop(price, **kw)`, `buy_limit(price, **kw)`, `sell_limit(price, **kw)`, `cancel(side=0)`,
  `set_stop(price)`, `set_target(price)`, `exit()`. The order keywords are the per-order values of section 8.
- An entry order while a position is open raises an error, unless `ctx.exit()` is called in the same call (reverse).
- `active=mask`: while the engine is idle (flat, nothing pending) the callback is only called on bars where the mask
  is True; while a position or an order is live it is called on every bar.

## 6. Fill rules (the same for every test)

1. A strategy sees closed bars only. Whatever is decided at the close of bar i acts from bar i+1.
2. Market entry: the open of the next bar. If that bar is not allowed (session rules) the order is dropped, not
   carried forward.
3. Stop entry: fills when a later bar trades at or through the stop price; at the stop price, or at the bar's open
   if the bar opens beyond it.
4. Limit entry: fills only when a later bar trades strictly through the limit; at the limit price, or at the bar's
   open if the bar opens beyond it in the trader's favour. A touch does not fill.
5. Protective stop: exits when a bar's adverse extreme reaches it; at the stop price, or at the open if the bar gaps
   beyond it.
6. Profit target: exits only when a bar trades strictly through it; at the target price, never better.
7. Stop and target reached in one bar: the stop is taken.
8. Entry bar of a stop or limit entry: the protective stop counts (at the stop price) if the bar's adverse extreme
   reaches it; the target and the first target do not count. A market entry is filled at the open, so its entry bar
   is an ordinary full bar.
9. Slippage: every fill of a stop order (stop entry, protective stop exit) pays 1 tick = 0.25 points. Market, limit,
   target, time and end-of-day fills pay no slippage.
10. Costs: every trade pays 0.75 index points round trip on top. `net_pts = gross_pts - 0.75`, where `gross_pts` is
    measured between the fill prices (slippage included).
11. Two-sided orders: if both could fill in one bar, the one nearer to the open is taken first and the other is
    cancelled; two contradictory fills at the same open cancel each other.
12. A stop that is already on the wrong side of the market when the entry fills is hit at once, one tick beyond the
    price at which the entry order was filled (before the entry's own slippage tick): a market or limit entry loses
    0.25 + costs, a stop entry 0.50 + costs.
13. Changes to the stop (breakeven, trailing, first-target move, `ctx.set_stop`) are made at the close of a bar and
    count from the next bar. The built-in rules only ever tighten a stop.

Size is always one unit; P&L is in index points (about NQ points: $20 per point NQ, $2 per point MNQ).

## 7. Session rules

Default = intraday, usable on a Tradeify account:

1. Trading day: 18:00 ET to 16:15 ET. No bar that opens at or after 16:15 ET exists in the engine.
2. No entry on incomplete days (fewer than 370 regular-session 1-minute bars; the whole trading day).
3. No entry after `last_entry` (default `"15:55"`): a market order needs a bar that opens at or before it; a stop
   or limit order, which can fill anywhere inside a bar, needs a bar that ends at or before it. Optional
   `first_entry`: an entry needs a bar that opens at or after it.
4. Flat by 16:10 ET: an open position is closed at the close of the last bar that ends by 16:10 ET (exit reason
   `eod`): the 16:05 bar on 5-minute bars, the 16:09 bar on 1-minute bars, the bar ending 16:00 on 15- and 30-minute
   bars.
5. Pending entry orders are cancelled at that time; nothing is carried across the end of the trading day.
6. A position may be held from the 18:00 ET open through 16:10 ET (one trading day), never longer.
7. One position at a time. `max_trades_per_day=N` limits the entries per trading day.
8. An order decided on the bar that ends at 16:15 ET (after the cancel time) is a new order for the next trading
   day: a market order fills at the 18:00 ET open, a stop or limit order works in that trading day. A signal on any
   other bar that happens to be the last bar of its trading day (half days, source gaps) is dropped
   (`diag["dropped"]`), so a day that ends early never hands orders to the next day.

`allow_multi_day=True` (swing rules) lifts 4 to 6 and 8: positions run across days and weekends, a market order
fills at the next bar's open whatever day that is, an entry order with `expiry_bars` may wait across days, and a
position still open at the end of the data is closed there (`end_of_data`). Across a gap in the data a position's stop is checked against the next bar's open (fill rule 5).
Rules 1 to 3 still apply (set `last_entry=None` or a later time for entries near the close). Such a test is flagged
`tradeify_usable: false`.

## 8. Order and trade management reference

Per-order values. In `Signals`: scalars or per-bar arrays, shared by both sides or inside a side dict. In a callback:
keyword arguments of the order methods.

| Name | Meaning |
|---|---|
| `order` | `"market"`, `"stop"`, `"limit"` (or codes `eng.MARKET`, `eng.STOP`, `eng.LIMIT`, also as a per-bar array) |
| `price` | stop / limit price of the entry order |
| `stop` or `stop_pts` | protective stop as a price, or as points from the actual fill price |
| `target`, `target_pts` or `target_r` | target as a price, as points from the fill, or as a multiple of the initial risk |
| `tp1`, `tp1_pts` or `tp1_r` | optional first target: `tp1_frac` of the position is closed there and the stop is moved (`tp1_stop`) |
| `expiry_bars` | the entry order may fill in the next N bars |
| `expiry_time` | the entry order may fill only in bars that end by this ET time |
| `max_bars` | close at the close of the N-th bar held (the entry bar is bar 1), reason `bars` |
| `trail_pts`, `be_trigger_pts` | see below |

Without `expiry_bars` and `expiry_time` a stop or limit order works until the end of its trading day. A new order
replaces a waiting order of the same side. A NaN in any value that was given (or a distance that is not positive)
voids that signal (counted in `diag["void"]`); use +/-inf for "no stop / no target on this bar". The price of a
market order is ignored.

Run-level values (keyword arguments of `Signals` and `Callback`):

| Name | Default | Meaning |
|---|---|---|
| `exit_time` | None | close at the close of the last bar that ends by this ET time, reason `time`. A trade entered after that bar runs to the end of day |
| `max_bars` | None | as above, for every trade |
| `tp1_frac`, `tp1_stop` | 0.5, `"be"` | fraction closed at the first target; then the stop goes to the entry price (`"be"`), to entry + x points in the trade's favour (a number) or stays (`"keep"`) |
| `be_trigger_pts` / `be_trigger_r`, `be_offset_pts` | None, 0 | once the best price since entry is that far in profit, the stop moves to entry + offset |
| `trail_pts` / `trail_r` | None | trail the stop that far behind the best price since entry |
| `trail_trigger_pts` / `trail_trigger_r` | None | start trailing only after that much profit |
| `trail_long`, `trail_short` (`Signals` only) | None | per-bar stop prices; after each closed bar the stop is tightened to the value |
| `exit_long`, `exit_short` (`Signals` only) | None | exit signals, filled at the next open, reason `signal` |
| `last_entry`, `first_entry`, `allow_multi_day`, `max_trades_per_day` | `"15:55"`, None, False, None | session rules, section 7 |

"Best price since entry" uses closed bars: highs for a long, lows for a short; on the entry bar of a stop or limit
entry only the close.

## 9. Results

`eng.run(bars, strategy)` returns a `RunResult`: `trades` (DataFrame), `diag` (counts: `orders` placed, `fills`,
`void` signals with a NaN value, `dropped` signals that may not be carried into the next trading day, `conflicts`),
`path`, `session`, `rules`, `tradeify_usable`. If a strategy trades less than expected, look at `diag` first.

Trades table, one row per trade:

| Column | Meaning |
|---|---|
| `entry_time`, `exit_time` | ET with UTC offset. Entry: open of the bar in which the entry filled. Exit: end of the exit bar, or its open for a signal exit |
| `entry_day` | trading day of the entry (decides the split and the year) |
| `direction`, `order_type` | +1 / -1; market, stop or limit |
| `entry_price`, `exit_price` | fill prices including stop slippage; with a partial exit, `exit_price` is the fill of the rest |
| `exit_reason` | `stop`, `target`, `time`, `bars`, `signal`, `eod`, `end_of_data` |
| `gross_pts`, `slippage_pts`, `cost_pts`, `net_pts` | gross between fills (weighted over the two parts of a partial exit); slippage already inside gross (for information); 0.75; gross - cost |
| `bars_held`, `minutes_held` | bars in which the position was open; exit time minus entry time |
| `mae_pts`, `mfe_pts` | largest adverse / favourable move in points from the entry price over the bars held, both >= 0. Entry bar of a stop or limit entry: adverse extreme and close only. Stop exit bar: adverse up to the stop price (the exit's slippage tick is not in it, so a stopped trade loses one tick more than its MAE), favourable only its open. Target exit: favourable up to the target |
| `stop_price`, `risk_pts`, `r_multiple` | initial stop, points from the entry fill to it, `net_pts / risk_pts` (NaN without a stop) |
| `target_price`, `partial_exit`, `partial_price`, `partial_frac` | initial target; first-target details |
| `signal_bar`, `entry_bar`, `exit_bar`, `split` | bar indices; `IS` or `OOS` |

Fixed split, the same for every test: the complete regular-session days in the data are put in order (3,844 days,
2010-11-15 to 2026-10-30); the first 60% (2,306 days) are in-sample, the last 40% (1,538 days) out-of-sample.
`eng.SPLIT_DATE = "2020-03-18"` is the first OOS day. A trade belongs to the split of its entry trading day.

`eng.stats(trades)` returns `{"split_date", "IS": {...}, "OOS": {...}, "ALL": {...}}`; each split has

- `trades`, `mean_net_pts`, `std_net_pts`, `t_stat`, `p_one_sided` (mean > 0, Student t)
- `boot_ci95_mean` (percentile bootstrap, 2,000 resamples, fixed seed)
- `win_rate`, `profit_factor`, `mean_r` and `trades_with_stop`
- `mae_median_pts`, `mae_p90_pts`, `median_minutes_held`, `trades_per_year`
- `net_pts_by_year`, `trades_by_year`
- day-clustered test (several trades on one day are not independent): `days_traded`, `day_mean_net_pts`,
  `day_std_net_pts`, `day_t_stat`, `day_p_one_sided` on the daily sums of net points
- extras: `total_net_pts`, `mean_gross_pts`, `worst_day_net_pts`, `max_drawdown_pts`

`None` means not defined (no trades, one trade, no losing trade). `eng.format_stats(st)` prints a short table.

## 10. Runner and output files

```python
eng.run_config(config_id, family, params, strategy_fn, resolution,
               overwrite=False, check_lookahead=True, notes=None, verbose=True)
```

- `strategy_fn(bars, params)` returns `eng.Signals` or `eng.Callback`.
- Writes `research3/out/results/<config_id>.json` (stats, params, data file, engine version and hash, session and
  trade rules, `tradeify_usable`, costs, diagnostics, lookahead check, run time) and
  `research3/out/trades/<config_id>.csv` (the trades table). The folders are created.
- An existing file is never replaced: `FileExistsError`, unless `overwrite=True`.
- `config_id`: letters, digits, `.`, `_`, `-`; it is the file name, so keep it unique.
- `check_lookahead=True` (default) first runs `check_no_lookahead` on the first 500 trading days (one to three
  seconds) and raises `LookaheadError`, writing nothing, if the strategy's past signals, orders or trades change when
  later bars are removed. `False` skips it and the JSON says `"skipped"`.
- Returns the JSON content as a dict.

## 11. Things to know

- Times: a signal array is indexed by the bar that just closed. `bars.ends_at("10:00")` marks the bar after whose
  close you act at 10:00; `bars.opens_at("10:00")` marks the bar that starts at 10:00.
- A market signal on the bar that ends at 16:15 is filled at the 18:00 open of the next trading day (session rule
  8): this is how to enter at the evening open (`bars.ends_at("16:15")`). Mask your signals by time if you do not
  want that.
- With `exit_time`, also set `last_entry` no later than it; a trade entered after the exit time stays until 16:10.
- `stop=` is a price and stays where it is when the entry gaps; `stop_pts=` follows the actual fill. `target_r` uses
  the actual risk (fill to stop).
- A stop-in, stop-out trade costs 0.25 + 0.25 + 0.75 = 1.25 points; a market-in, target-out trade 0.75.
- Use the engine's stats only. Do not compute your own t-values or move the split.
- The split date falls in March 2020, so the first OOS weeks are the COVID crash; look at `net_pts_by_year`.
- The data is a Nasdaq-100 index CFD without volume. Anything that needs volume cannot be tested; the nine
  1-minute moves above 3% are not special-cased.
- `strategy_fn` must be deterministic and must not keep state between calls.
- The lookahead check compares signal arrays, closed trades and entries on data truncated at random bars, and also
  right where the strategy acts: for path (a) right after bars with an entry or exit signal, for path (b) it re-runs
  the callback with everything after such a bar made unknown and compares what the callback did (orders with their
  values, exits, stop and target changes, cancels). The second part is what finds a value that is exactly one bar
  ahead (`np.roll(x, -1)`, `shift(-1)`, `x[min(i + 1, n - 1)]`, a centered window): random cuts alone almost never
  do when the signals are sparse. It is a sample (12 + 12 cuts in the first 500 trading days), not a proof: still
  use arrays at `i` or earlier only. It cannot see `bars.incomplete`: that flag is known for the whole day by design.
- Speed: path (a) on 16 years of 5-minute bars takes about 0.3 to 1.2 s (signals, simulation and stats); loading the
  5-minute bars 0.3 to 0.8 s; a callback run 0.4 to 1 s plus the work of the callback; 1-minute bars load in about
  2 s and run in 1 to 6 s. Memory: about 0.4 GB per process on 5-minute bars, about 1 GB on 1-minute bars.
- `load_bars` is cached per process; reuse one process for many configurations of a family.

## 12. Tests

`python3 -I test_engine.py` (about 25 s): hand-built bars with hand-computed results for every fill, cost and session
rule; DST weeks in March and November; incomplete days; trading-day ids; resampling against a loop and against
`NSX_5m.npz`; every indicator against a pandas or loop reference; the fixed split; statistics; the runner; both
paths giving identical trades on real data; the engine against an independent plain simulator; the no-lookahead
property on the full data; session invariants at 1, 5, 15 and 30 minutes; the examples of this file;
and the run time.

`python3 -I test_engine_review.py` (about 2 minutes) is an independent review suite written from this file and
DATA_NOTES.md: hand-computed fills and session rules; every helper against brute force and against truncated data;
resampling minute by minute, also for resolutions that do not divide a day; a second plain simulator; long/short
mirror symmetry; leaking strategies that the lookahead check must catch; the statistics against scipy; and two
strategies with a result known in advance on the real 5-minute data (random entries average minus the cost; buy
09:30, sell 16:00 equals the open-to-close moves of the bars minus costs).
