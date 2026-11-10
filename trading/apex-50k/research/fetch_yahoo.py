"""Download recent intraday futures bars from Yahoo Finance's public chart endpoint and write a clean CSV.

Usage: python3 fetch_yahoo.py [--symbol MNQ=F] [--interval 5m] [--range 60d] [--out MNQ_5m.csv]

Yahoo keeps about 60 days of 5-minute bars and about 7 days of 1-minute bars. The series is the continuous
front month, not back-adjusted: the quarterly roll shows up as a price gap at a Sunday open. Rows with
missing prices and the still-forming last bar are dropped. The script prints the largest bar-to-bar gaps so
the roll and any bad prints can be checked by eye; it does not change prices.
"""
import argparse
import csv
import json
import urllib.request
from datetime import UTC, datetime

ap = argparse.ArgumentParser()
ap.add_argument("--symbol", default="MNQ=F")
ap.add_argument("--interval", default="5m")
ap.add_argument("--range", default="60d")
ap.add_argument("--out", default=None)
a = ap.parse_args()
step = {"1m": 60, "2m": 120, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600}[a.interval]
url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{a.symbol.replace('=', '%3D')}"
       f"?interval={a.interval}&range={a.range}&includePrePost=true")
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
data = json.load(urllib.request.urlopen(req, timeout=30))
res = data["chart"]["result"][0]
q = res["indicators"]["quote"][0]
rows = []
for i, ts in enumerate(res["timestamp"]):
    o, h, l, c, v = (q[k][i] for k in ("open", "high", "low", "close", "volume"))
    if None in (o, h, l, c) or ts % step:
        continue
    rows.append((ts, o, h, l, c, v or 0))
out = a.out or f"{a.symbol.split('=')[0]}_{a.interval}.csv"
with open(out, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
    for ts, o, h, l, c, v in rows:
        w.writerow([datetime.fromtimestamp(ts, UTC).isoformat(), o, h, l, c, v])
print(f"wrote {len(rows)} bars to {out}: {datetime.fromtimestamp(rows[0][0], UTC)} .. {datetime.fromtimestamp(rows[-1][0], UTC)}")
gaps = sorted(((abs(rows[i][1] - rows[i - 1][4]), rows[i][0], rows[i][0] - rows[i - 1][0]) for i in range(1, len(rows))), reverse=True)
print("largest open-vs-previous-close gaps (check for the contract roll and bad prints):")
for g, ts, dt in gaps[:6]:
    print(f"  {g:9.2f} pts at {datetime.fromtimestamp(ts, UTC).isoformat()} after {dt // 60} min")
