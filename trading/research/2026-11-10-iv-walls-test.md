# IV Walls test, 2026-11-10

Fading the standard "IV walls" lost money after costs in all 12 versions tested, in both halves of 16 years. A first pass by one script; the shared test engine will re-run it independently.

## What was tested

- **The claim:** an Instagram reel by @atraintrades (2026-09-15) shows "90% Winrate Quant Strategy", a P&L screenshot and the caption "Can't beat the IV Walls". It gives no rules, trade list, period or audit.
- **The seller's guide** (2 pages): walls come from ETF options data (QQQ for NQ), are drawn each afternoon and hold for the next session. Short at the upper wall with the stop above it, long at the lower wall with the stop below it, target a multiple of risk "such as 5R". The wall formula itself is proprietary.
- **The standard public form, tested here:** wall = prior 16:00 ET close ± that close × VXN ÷ 100 ÷ √252, the one-day move that Nasdaq-100 options imply (EM). VXN is the prior day's close (FRED VXNCLS).
- **Trade:** a limit order at each wall, fading it; first touch only; stop 0.10 or 0.25 EM beyond the wall; target 5R, the prior close or 1R; flat at 16:00 ET. Fills need a trade through the wall; a bar that hits stop and target counts as the stop.
- **Costs:** 0.75 points per trade, plus 0.25 on stop exits.
- **Data:** 1-minute Nasdaq-100 index CFD bars (histdata.com NSXUSD), 2010-11-16 to 2026-10-30, 3,841 sessions. It tracks NQ futures (daily return correlation 0.976). Out-of-sample starts 2020-03-18.
- **Rules were fixed first:** all 12 versions, the primary one and the two side tests were written down before any result was computed.

## Do the walls hold?

- **Close:** price finished the day beyond a wall on 856 of 3,841 days (22.3%). A fair one-standard-deviation band would be beaten on about 32% of days, so options priced in more movement than happened.
- **Touch:** price reached a wall (or opened beyond one) on 1,540 days (40.1%).
- **After a touch:** on 56% of those days price also closed beyond a wall. Reaching a wall was more often followed by continuation than by a reversal.

## Fading the walls

Mean net points per trade (1 NQ point = $20 on NQ, $2 on MNQ).

| Version | Trades | Wins | All years | In-sample | Out-of-sample | Out-of-sample t |
|---|---|---|---|---|---|---|
| All hours, stop 0.10 EM, target 5R | 1,530 | 19.0% | -2.30 | -0.59 | -4.68 | -2.10 |
| All hours, stop 0.10 EM, target prior close | 1,530 | 16.2% | -1.48 | -0.18 | -3.29 | -1.12 |
| All hours, stop 0.10 EM, target 1R | 1,530 | 46.9% | -1.46 | -1.32 | -1.66 | -1.44 |
| All hours, stop 0.25 EM, target 5R | 1,530 | 29.3% | -3.66 | -1.22 | -7.06 | -1.53 |
| All hours, stop 0.25 EM, target prior close | 1,530 | 29.6% | -4.16 | -1.58 | -7.75 | -1.79 |
| All hours, stop 0.25 EM, target 1R | 1,530 | 44.6% | -3.49 | -2.12 | -5.40 | -2.01 |
| Regular session, stop 0.10 EM, target 5R | 1,285 | 18.8% | -3.17 | -1.68 | -5.34 | -2.31 |
| Regular session, stop 0.10 EM, target prior close | 1,285 | 16.8% | -2.29 | -1.01 | -4.13 | -1.40 |
| Regular session, stop 0.10 EM, target 1R | 1,285 | 45.8% | -1.82 | -1.62 | -2.12 | -1.72 |
| Regular session, stop 0.25 EM, target 5R | 1,285 | 30.6% | -4.73 | -2.11 | -8.51 | -1.84 |
| Regular session, stop 0.25 EM, target prior close | 1,285 | 30.7% | -5.11 | -2.25 | -9.26 | -2.11 |
| Regular session, stop 0.25 EM, target 1R | 1,285 | 42.2% | -6.06 | -3.09 | -10.37 | -3.64 |
| Side test: target 0.10 EM, stop 0.50 EM (high win rate) | 1,530 | 74.6% | -3.22 | -2.28 | -4.53 | -1.80 |
| Side test: primary version with 20-day historical volatility in place of VXN | 2,132 | 16.7% | -2.51 | -1.57 | -3.87 | -2.45 |

- **Primary version** (all hours, stop 0.10 EM, target 5R): 1,530 trades, 19% won, average win +55.2 points and average loss -15.8. Mean -2.30 points per trade (t -2.33); out-of-sample -4.68 over 640 trades.
- **No version passed.** Every one has a negative mean in-sample and out-of-sample; every Holm-corrected p-value is 1.00.
- **With equal stop and target (1R)** the fade won 46.9% of the time at 0.10 EM and 44.6% at 0.25 EM. A level that price respects would win more than half.
- **A high win rate is easy and proves nothing.** A small target with a wide stop won 74.6% of 1,530 trades and still lost 4,930 points over 16 years (average win +14.4, average loss -54.9). Out-of-sample it won 75.5% and lost 2,896 points.
- **Implied volatility added nothing.** Walls built from plain historical volatility did about the same (-2.51 points per trade).
- **Size of the swings:** the median wall distance was 95 points. Adverse movement inside a trade was 8 points at the median and 30 at the 90th percentile for the 0.10 EM stop.

## Limits

- **Not the seller's exact levels.** His walls come from proprietary software and are traded with discretion ("let the market confirm the setup"). This tests the standard formula with mechanical entries. His daily levels could be logged and forward-tested with the prediction journal.
- **VXN is a 30-day measure.** A one-day option price can differ from it, most on event days.
- **Index CFD, not the future:** levels differ by a small basis; points are used as NQ points.
- **One script, one pass.** A date-handling bug was caught by a sanity check (too few wall touches) and fixed before these results; the engine run repeats the test independently.

Rules as fixed in advance: `code/iv_walls_PREREG.md`. Script: `code/iv_walls_test.py`. Data scripts: `code/fetch_histdata.py`, `code/build_data.py`.
