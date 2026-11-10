# NQ edge tests, 2026-11-03

None of the six rules passed. No rule here has earned the right to be traded or turned into signals.

The rules, parameters and pass bar were fixed before any data was looked at. They are in `2026-11-03-preregistration.md`, and every trade had to fit the Tradeify flat-by-16:45 rule.

## Data

- **Daily:** Yahoo NQ=F, 2000-09-18 to 2026-11-02. A daily bar runs from the 18:00 ET open to the ~16:00 ET settlement, checked against hourly bars.
- **Hourly:** NQ=F, 2024-06 to 2026-11.
- **5-minute:** MNQ=F, 2026-08 to 2026-11.
- **Cross-check:** TradingView CME_MINI:NQ1! daily bars matched Yahoo exactly outside roll weeks.

## Method

- Every trade pays 0.75 NQ points round trip, about $1.50 per MNQ.
- In-sample is 2000-2016 and out-of-sample is 2017 to now. The hourly test uses the first 60% of sessions in-sample and the last 40% out-of-sample.
- A Holm correction covers all six tests.

## Results

| Test | Rule | Out-of-sample trades | Mean net points | One-sided p | Holm p | Verdict |
|---|---|---|---|---|---|---|
| T1 | Turn of month, long the session | 473 | +11.2 | 0.109 | 0.37 | Fail: not significant; in-sample mean negative; no better than NQ's own drift |
| T2 | FOMC day, long to 13:59 ET | 77 | +45.7 | 0.015 | 0.089 | Fail: too few trades (needs 100); does not survive Holm; dropping the top 3 trades gives p 0.07 |
| T3a | RSI(2) < 10 above the 200-day average, long next session | 160 | +24.3 | 0.093 | 0.37 | Fail: not significant |
| T3b | RSI(2) < 10 below the 200-day average, long next session | 63 | +97.6 | 0.026 | 0.13 | Fail: too few trades; in-sample mean negative; 36 of 63 trades from 2022 |
| T4a | First hour beyond ±0.4%, follow it from 10:30 to the close | 112 | +10.0 | 0.32 | 0.63 | Fail |
| T4b | Same trigger, fade it | 112 | −11.5 | 0.71 | 0.71 | Fail |

## Notes

- **Independent checks:** T2 and T3 were rebuilt from the pre-registration in separate scripts. Both reproduced the numbers exactly and found no lookahead, but judged neither tradeable.
- **T4 data:** the CME hourly bars start on the hour, so the 09:30-10:30 first hour could not be measured from them. T4 used QQQ hourly bars as a proxy instead, after a pre-committed check that their first-hour returns track NQ (correlation 0.9997). A 15-session exact check on MNQ 5-minute bars agreed.
- **Size of the swings:** the typical adverse move inside a trade before its exit was 90-190 NQ points at the median and 330-530 points at the 90th percentile. That is $180-380 per MNQ at the median, so even a winning trade from these rules would usually go more than $199 against you first.

Scripts, trade lists and quality reports were in the session scratchpad (`research2/`) and are not committed.
