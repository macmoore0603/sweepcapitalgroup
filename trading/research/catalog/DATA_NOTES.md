# Data notes (read before using the bars)

Files (numpy .npz, arrays `t` = bar OPEN time in epoch seconds UTC, `o`, `h`, `l`, `c`; no volume):
- `NSX_1m.npz`: 5,320,151 one-minute bars, 2010-11-14 18:01 ET to 2026-10-30 16:13 ET.
- `NSX_5m.npz`: 1,097,862 five-minute bars built from the 1-minute bars (buckets on :00, :05, ...).
- `NSX_5m.csv`: the same 5-minute bars with ET ISO timestamps.

What it is: histdata.com NSXUSD, a Nasdaq-100 index CFD (bid quotes), not the NQ future itself.
- Checked against NQ=F futures: daily 16:00-to-16:00 ET return correlation 0.976 over 3,919 days (0.990 without 53 days that
  differ by more than 1%, mostly futures roll days); hourly return correlation 0.976 over 12,955 hours in 2024-06..2026-10
  (0.995 without 29 hours); median absolute hourly difference 0.3 basis points.
- Price level is within about 0.5% of the NQ future (the future carries a small premium). Use P&L in index points as NQ points
  ($20 per point NQ, $2 per point MNQ). Never mix NSX price levels with futures price levels.
- Timestamps were converted to real New York time (the source changed its clock convention in 2019; verified against the
  09:30 ET open in every year, including the weeks when US and EU daylight-saving dates differ). Convert `t` with
  America/New_York for every time-of-day rule.

Trading hours in the data: Sunday open 18:00 ET. The daily break starts 16:15 ET from 2019 on (17:00 ET in 2015-2018, shorter
breaks earlier) and the next session starts 18:00 ET. For one rule across all years, treat 16:15 ET as the end of the trading
day: no bar after 16:15 ET may be used, and intraday strategies must be flat by the close of the last bar that ends by
16:10 ET (Tradeify's own deadline is 16:45 ET, so this is stricter).

Gaps: 253 of 4,110 regular sessions (09:30-16:00 ET) have fewer than 350 of the 390 one-minute bars: 117 in 2023 (source
gaps) and the rest mostly US holidays and half days. Treat a day with fewer than 370 regular-session one-minute bars as
incomplete: take no trades that day. There are 9 one-minute moves above 3% (flash moves or bad ticks); do not special-case them.

No volume: any rule that needs volume (true VWAP, volume spikes, volume profile) cannot be computed on these bars. An
equal-weighted average of typical price since the session start is NOT VWAP; label it as a time-weighted proxy if used.

Other data: `../../research2/data/NQ_F_1d.csv` (NQ=F daily 2000-09..2026-11, with volume), `NQ_F_1h.csv` (NQ=F hourly
2024-06..2026-11, with volume), `MNQ_F_5m.csv` (MNQ 5-minute, 49 sessions Aug-Oct 2026, with volume).
