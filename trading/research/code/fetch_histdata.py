"""Polite, resumable download of histdata.com free 1-minute NSXUSD (Nasdaq-100) bar files.
Usage: python3 -I fetch_histdata.py OUT_DIR FIRST_YEAR LAST_FULL_YEAR CURRENT_YEAR LAST_MONTH
One request pair per file, sequential, with a pause; stops after 3 consecutive failures."""
import re, subprocess, sys, time, os
out, y0, y1, ycur, mlast = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
BASE = "https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/nsxusd/"
jar = os.path.join(out, "cookies.txt")
jobs = [(str(y), None) for y in range(y0, y1 + 1)] + [(str(ycur), m) for m in range(1, mlast + 1)]
fails = 0
for year, month in jobs:
    name = f"NSXUSD_M1_{year}{'' if month is None else f'{month:02d}'}.zip"
    dest = os.path.join(out, name)
    if os.path.exists(dest) and os.path.getsize(dest) > 1000:
        print("have", name); continue
    page = BASE + year + ("" if month is None else f"/{month}")
    html = subprocess.run(["curl", "-sS", "-m", "60", "-c", jar, "-b", jar, page], capture_output=True, text=True).stdout
    def field(n):
        m = re.search(r'name="%s"[^>]*value="([^"]*)"' % n, html)
        return m.group(1) if m else None
    tk = field("tk")
    if not tk:
        print("no token", name); fails += 1
    else:
        data = "&".join(f"{k}={field(k)}" for k in ["tk", "date", "datemonth", "platform", "timeframe", "fxpair"])
        subprocess.run(["curl", "-sS", "-m", "180", "-c", jar, "-b", jar, "-e", page, "-d", data, "-o", dest, "https://www.histdata.com/get.php"])
        ok = os.path.exists(dest) and open(dest, "rb").read(2) == b"PK"
        print(("ok  " if ok else "BAD ") + name, os.path.getsize(dest) if os.path.exists(dest) else 0, flush=True)
        if ok: fails = 0
        else:
            fails += 1
            if os.path.exists(dest): os.remove(dest)
    if fails >= 3:
        print("stopping: 3 consecutive failures"); break
    time.sleep(4)
