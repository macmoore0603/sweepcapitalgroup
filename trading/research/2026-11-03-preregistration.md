PRE-REGISTRATION (fixed before any result is seen; do not change rules, parameters or pass bars after looking at data).
Account constraint: every trade must open and close within one CME session (18:00 ET to 17:00 ET) and be flat by 16:45 ET (Tradeify). No overnight holds across the 17:00 break.
Split: daily tests — in-sample (IS) 2000-09-01..2016-12-31, out-of-sample (OOS) 2017-01-01..latest. Hourly test — IS = first 60% of sessions, OOS = last 40%.
Costs per round trip, in NQ index points: 0.75 points (1 tick of slippage each side = 0.5 points, plus commission of about 0.25 points per contract equivalent; for MNQ that is about $1.50 per contract round trip). Apply to every trade.
Pass bar for each test (all must hold): OOS mean net points per trade > 0 with one-sided p < 0.05 AFTER Holm correction across all 6 tests; OOS trades >= 100 (daily) or >= 60 (hourly); IS mean net > 0 (same sign); result survives independent recomputation. Report everything, passing or not.
Tests:
T1 Turn of month (daily): long from the session open to the session close (session = CME trading day) on the last trading day of each month and the first 3 trading days of the next month. One trade per such session.
T2 Pre-FOMC (daily): long the CME session that ends on the day of each scheduled FOMC statement, from session open to 13:59 ET that day (before the 14:00 statement). Use only scheduled FOMC meeting dates from the Federal Reserve's official calendars (federalreserve.gov), 2000+. If intraday 13:59 prices are unavailable for old years, use the session open to the 1h bar close nearest before 14:00 where hourly data exists, and for daily-only years use open to close and label it.
T3a Dip in uptrend (daily): if the prior session close > its 200-session simple moving average and the 2-period RSI (Wilder) of closes < 10, go long the next session from open to close.
T3b Dip in downtrend (daily): same as T3a but prior close < 200-session SMA.
T4a First-hour momentum (1h, 2 years): if the RTH first hour (09:30-10:30 ET) return exceeds +0.4% go long at 10:30, if below -0.4% go short at 10:30; exit at 15:55 ET (or the last bar close before 16:00). One trade per day at most.
T4b First-hour reversal (1h): the opposite direction of T4a with the same trigger and exit.
