"""Run the July NQ setups and seeded random-entry controls through the July engine on real bars.

Usage:
  python3 -I research/run_real.py --nqcopilot ~/Mac/src --bars MNQ_5m.csv --out out \
      [--symbol MNQ] [--roll 2026-09-13T21:00Z ...] [--random 20]

--nqcopilot is the src folder of the nqcopilot package (the July engine, macmoore0603/Mac PR #1).
Each --roll splits the bars at a contract roll (the first bar of the new contract) so no indicator,
level or trade spans two contract months. Bars whose open (and high or low) is a lone spike more than
1% beyond both the previous close and the bar's own close are clamped to the bar's real range.

The replay keeps the July "conservative" limits ($100 risk per trade, $300 daily stop, 3 trades a day,
2-loss streak, $400 profit lock, 8-60 point stops, first 5 minutes and lunch blocked) but gives the account
an unlimited drawdown, so the replay records every day's trades; the planner then applies the real Apex
rules. The random control replaces only the setup detector: on a seeded share of bars it proposes a long
or short with the July structural stop and 1.5R / 3R targets, and everything after that (score and stop
gates, risk blockers, sizing, fills, scale-out, breakeven, time stop, session flatten) is the same engine.
The entry rate is calibrated so the control takes about as many trades as the setups.

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
        s = sg._build_setup("Random", d, entry, stop, entry + d * 1.5 * risk, entry + d * 3.0 * risk, 80.0,
                            ctx.spec, ["random control"])
        return [s] if s else []
    return detect


def run(detect):
    pb.detect_all = detect
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


def write_tv_csv(trades, path):
    pv = SPEC.point_value
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Trade #", "Type", "Date and time", "Signal", "Price USD", "Position size (qty)",
                    "Net P&L USD", "Favorable excursion USD", "Adverse excursion USD"])
        for n, t in enumerate(trades, 1):
            side = "long" if t.direction > 0 else "short"
            fav = abs(t.mfe_points) * pv * t.quantity
            adv = -abs(t.mae_points) * pv * t.quantity
            for typ, ts, px in (("Entry", t.entry_ts, t.entry_price), ("Exit", t.exit_ts, t.exit_price)):
                w.writerow([n, f"{typ} {side}", et(ts), t.setup_name, f"{px:.2f}", t.quantity,
                            f"{t.net_pnl:.2f}", f"{fav:.2f}", f"{adv:.2f}"])


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

target, lo, hi, p = max(len(sig), 1), 0.0005, 0.2, 0.02
for _ in range(8):
    n = len(run(random_detect(p, 999)))
    if abs(n - target) <= max(2, 0.1 * target):
        break
    lo, hi = (p, hi) if n < target else (lo, p)
    p = (lo + hi) / 2
summary["random_entry_rate"] = p
summary["random"] = []
for seed in range(1, args.random + 1):
    tr = run(random_detect(p, seed))
    write_tv_csv(tr, out_dir / f"random_{seed:02d}.csv")
    s = stats(tr) | {"seed": seed}
    summary["random"].append(s)
    print(f"random {seed:02d}: {s['trades']} trades, net per contract {s['net_per_trade_per_contract']}")
(out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
print(f"entry rate {p:.5f}; fixed bars {fixes}; wrote {out_dir}")
