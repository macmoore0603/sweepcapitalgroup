"""Run the July NQ setups and seeded random-entry controls through the July engine on real bars.

Usage:
  python3 -I research/run_real.py --nqcopilot ~/Mac/src --bars MNQ_5m.csv --out out \
      [--symbol MNQ] [--roll 2026-09-13T21:00Z ...] [--random 20]

--nqcopilot is the src folder of the nqcopilot package (the July engine, macmoore0603/Mac PR #1).
Each --roll splits the bars at a contract roll so no indicator, level or trade spans two contract months.
Give the time of the first bar of the new contract: Yahoo's continuous series switches on a weekday, not at a
weekend open (MNQ=F moved from September to December at 2026-09-15T07:30Z), so look for a one-bar jump in
the fetch script's gap list that is not a weekend gap. Bars whose open (and high or low) is a lone spike more
than 1% beyond both the previous close and the bar's own close are clamped to the bar's real range.

The replay keeps the July "conservative" limits ($100 risk per trade, $300 daily stop, 3 trades a day,
2-loss streak, $400 profit lock, 8-60 point stops, first 5 minutes after the open blocked; lunch is only a
soft warning in the July engine, not a block) but gives the account an unlimited drawdown, so the replay
records every day's trades; the planner then applies the firm's rules. Both arms are blocked from proposing
entries from 15:50 ET (the July engine only flattens during 15:50-16:00 and otherwise would hold a late entry
past the close). The random control replaces only the setup detector: on a seeded share of bars it proposes a
long or short with the July structural stop, 1.5R / 3R targets and a score of 22 plus the July confluence
points (the Trend Pullback formula), so it faces the same score gate, stop gate, risk blockers, sizing,
fills, scale-out, breakeven and time stop. The entry rate is calibrated on the mean trade count over 30
calibration seeds that are separate from the 20 reported seeds.

Run-up and drawdown are rebuilt from the bars between entry and exit. On a stop exit the exit bar's
favorable extreme is ignored and the adverse excursion is capped at the fill (the engine assumes the stop came
first on that bar). Results are also reported in R (net P&L over planned risk) with a bootstrap interval.

Writes signals.csv and random_NN.csv in TradingView "List of trades" layout, plus summary.json. Feed them to
the planner, e.g. node planner/cli.mjs --trades out/signals.csv --unit micro --sweep
"""
import argparse
import csv
import dataclasses
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ap = argparse.ArgumentParser()
ap.add_argument("--nqcopilot", required=True)
ap.add_argument("--bars", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--symbol", default="MNQ")
ap.add_argument("--roll", action="append", default=[], help="ISO time of the first bar of a new contract")
ap.add_argument("--random", type=int, default=20)
args = ap.parse_args()
sys.path.insert(0, str(Path(args.nqcopilot).expanduser()))

from nqcopilot.apex import APEX_50K_EVAL, AccountState, RiskLimits  # noqa: E402
from nqcopilot.backtest import BacktestConfig, run_backtest  # noqa: E402
from nqcopilot.contracts import get_contract  # noqa: E402
from nqcopilot.data import load_csv  # noqa: E402
from nqcopilot.bars import Session, classify_session  # noqa: E402
import nqcopilot.playbook as pb  # noqa: E402
import nqcopilot.signals as sg  # noqa: E402

ET = ZoneInfo("America/New_York")
SPEC = get_contract(args.symbol)
out_dir = Path(args.out)
out_dir.mkdir(parents=True, exist_ok=True)

bars = load_csv(args.bars)
clean, fixes = [bars[0]], []
for prev, b in zip(bars, bars[1:]):
    ref_hi, ref_lo = max(prev.close, b.close), min(prev.close, b.close)
    if b.open > ref_hi * 1.01 and b.high == b.open:
        fixes.append(str(b.ts))
        b = dataclasses.replace(b, open=max(b.low, min(prev.close, b.close)), high=max(b.low, b.close, min(prev.close, b.close)))
    elif b.open < ref_lo * 0.99 and b.low == b.open:
        fixes.append(str(b.ts))
        b = dataclasses.replace(b, open=min(b.high, max(prev.close, b.close)), low=min(b.high, b.close, max(prev.close, b.close)))
    clean.append(b)
bars = clean
cuts = sorted(datetime.fromisoformat(r.replace("Z", "+00:00")) for r in args.roll)
segments, rest = [], bars
for cut in cuts:
    segments.append([b for b in rest if b.ts < cut])
    rest = [b for b in rest if b.ts >= cut]
segments.append(rest)
segments = [s for s in segments if len(s) > 200]

PROFILE = dataclasses.replace(APEX_50K_EVAL, drawdown_amount=10_000_000.0, threshold_lock=None, profit_target=None)
LIMITS = RiskLimits()
CFG = BacktestConfig(stop_on_breach=False)
REAL_DETECT = pb.detect_all
LATE = {Session.CLOSING, Session.POST_CLOSE, Session.MAINTENANCE}


def no_late_entries(detect):
    def wrapped(ctx):
        return [] if classify_session(ctx.bar.ts) in LATE else detect(ctx)
    return wrapped


def u32(*xs):
    """Deterministic hash of the inputs to [0, 1)."""
    h = 2166136261
    for x in xs:
        for byte in int(x).to_bytes(8, "little", signed=True):
            h = ((h ^ byte) * 16777619) & 0xFFFFFFFF
    h ^= h >> 15
    h = (h * 2246822519) & 0xFFFFFFFF
    h ^= h >> 13
    return h / 4294967296.0


def random_detect(p, seed):
    def detect(ctx):
        ts = int(ctx.bar.ts.timestamp())
        if u32(seed, ts, 1) >= p:
            return []
        d = 1 if u32(seed, ts, 2) < 0.5 else -1
        entry = ctx.price
        stop = sg._stop_from_structure(ctx, d > 0)
        risk = abs(entry - stop)
        score = 22.0 + sg._confluence(ctx, d)[0]  # the Trend Pullback score formula, so the score gate applies
        s = sg._build_setup("Random", d, entry, stop, entry + d * 1.5 * risk, entry + d * 3.0 * risk, score,
                            ctx.spec, ["random control"])
        return [s] if s else []
    return detect


def run(detect):
    pb.detect_all = no_late_entries(detect)
    try:
        trades = []
        for seg in segments:
            res = run_backtest(seg, SPEC, AccountState.fresh(PROFILE), limits=LIMITS, config=CFG)
            trades.extend(res.trades)
        return trades
    finally:
        pb.detect_all = REAL_DETECT


def et(ts):
    return ts.astimezone(ET).strftime("%Y-%m-%d %H:%M")


BARS = [b for seg in segments for b in seg]
IDX = {b.ts: i for i, b in enumerate(BARS)}
STOP_EXITS = {"stop", "gap_through_stop", "breakeven_stop"}


def excursions(t):
    """(favorable, adverse) in points per contract, rebuilt from the bars the position was open."""
    i0, i1 = IDX[t.entry_ts], IDX[t.exit_ts]
    mfe = mae = 0.0
    for i in range(i0, i1 + 1):
        b = BARS[i]
        fav = (b.high - t.entry_price) if t.direction > 0 else (t.entry_price - b.low)
        adv = (t.entry_price - b.low) if t.direction > 0 else (b.high - t.entry_price)
        if i == i1 and t.exit_reason in STOP_EXITS:
            fav = 0.0
            adv = min(adv, max(0.0, (t.entry_price - t.exit_price) * t.direction))
        mfe, mae = max(mfe, fav), max(mae, adv)
    return mfe, mae


def write_tv_csv(trades, path):
    pv = SPEC.point_value
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Trade #", "Type", "Date and time", "Signal", "Price USD", "Position size (qty)",
                    "Net P&L USD", "Favorable excursion USD", "Adverse excursion USD"])
        for n, t in enumerate(trades, 1):
            side = "long" if t.direction > 0 else "short"
            mfe, mae = excursions(t)
            fav = mfe * pv * t.quantity
            adv = -mae * pv * t.quantity
            for typ, ts, px in (("Entry", t.entry_ts, t.entry_price), ("Exit", t.exit_ts, t.exit_price)):
                w.writerow([n, f"{typ} {side}", et(ts), t.setup_name, f"{px:.2f}", t.quantity,
                            f"{t.net_pnl:.2f}", f"{fav:.2f}", f"{adv:.2f}"])


def mean_ci(xs, reps=4000):
    """Mean, 95% bootstrap interval and t statistic."""
    import random
    import statistics
    if len(xs) < 2:
        return {"mean": xs[0] if xs else None, "ci95": None, "t": None}
    rng = random.Random(7)
    boots = sorted(statistics.fmean(rng.choices(xs, k=len(xs))) for _ in range(reps))
    sd = statistics.stdev(xs)
    return {"mean": statistics.fmean(xs), "ci95": [boots[int(0.025 * reps)], boots[int(0.975 * reps) - 1]],
            "t": statistics.fmean(xs) / (sd / len(xs) ** 0.5) if sd > 0 else None}


def stats(trades):
    n = len(trades)
    per = [t.net_pnl / t.quantity for t in trades]
    wins = [x for x in per if x > 0]
    gross_l = -sum(x for x in per if x <= 0)
    by = {}
    for t in trades:
        by.setdefault(t.setup_name, []).append(t.net_pnl / t.quantity)
    return {
        "trades": n,
        "win_rate": len(wins) / n if n else None,
        "net_per_trade_per_contract": sum(per) / n if n else None,
        "profit_factor": sum(wins) / gross_l if gross_l > 0 else None,
        "net_total_as_traded": sum(t.net_pnl for t in trades),
        "r": mean_ci([t.r_multiple for t in trades]),
        "by_setup": {k: {"n": len(v), "net_per_contract": sum(v) / len(v)} for k, v in sorted(by.items())},
    }


summary = {
    "bars": len(bars),
    "fixed_bars": fixes,
    "segments": [[str(s[0].ts), str(s[-1].ts), len(s)] for s in segments],
}
sig = run(REAL_DETECT)
write_tv_csv(sig, out_dir / "signals.csv")
summary["signals"] = stats(sig)
print("signals:", json.dumps(summary["signals"]))

import statistics  # noqa: E402

target, lo, hi = max(len(sig), 1), 0.0005, 0.3
CAL = range(1000, 1030)
for _ in range(12):
    p = (lo + hi) / 2
    m = statistics.fmean(len(run(random_detect(p, s))) for s in CAL)
    lo, hi = (p, hi) if m < target else (lo, p)
p = (lo + hi) / 2
summary["random_entry_rate"] = p
summary["calibration"] = {"target_trades": target, "seeds": [CAL.start, CAL.stop - 1]}
summary["random"] = []
for seed in range(1, args.random + 1):
    tr = run(random_detect(p, seed))
    write_tv_csv(tr, out_dir / f"random_{seed:02d}.csv")
    s = stats(tr) | {"seed": seed}
    summary["random"].append(s)
    print(f"random {seed:02d}: {s['trades']} trades, mean R {s['r']['mean']}")
summary["random_trade_counts"] = [r["trades"] for r in summary["random"]]
summary["random_mean_trades"] = statistics.fmean(summary["random_trade_counts"])
(out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
print(f"entry rate {p:.5f}; fixed bars {fixes}; wrote {out_dir}")
