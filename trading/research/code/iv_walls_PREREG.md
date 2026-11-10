# IV Walls test: rules fixed before any result was computed (2026-11-10)

Source of the idea: @atraintrades reel (2026-09-15) and the "ATrain Trades Guide: Understanding Implied Volatility (IV) Walls"
(2 pages). The guide says: walls come from ETF options data (QQQ for NQ), are drawn 4:30-6:00 PM ET, hold for the next
session at any time of day; short at the upper wall with the stop above it, long at the lower wall with the stop below it;
target a fixed multiple of risk "such as 5R". The exact wall formula is proprietary. Tested here: the standard public form.

Walls for trading day D: W = C +/- EM, where C = Nasdaq-100 close at 16:00 ET on the prior trading day,
EM = C x VXN / 100 / sqrt(252), VXN = that prior day's close of the Cboe Nasdaq-100 Volatility Index (FRED VXNCLS).
Both are known before 18:00 ET. Days without a prior VXN value or with an incomplete regular session are skipped.

Trade: a resting limit order at each wall, fading it (short the upper, long the lower), first touch only, one trade per wall
per day. Fill needs a 1-minute bar to trade through the wall. If the first bar of the window already opens beyond a wall,
that wall is skipped for the day. On the entry bar the stop counts and the target does not. Stop first if one bar hits both.
Stop exits pay 0.25 slippage. Every trade pays 0.75 points. Anything still open exits at the 16:00 ET close.

Variants (12, all reported, Holm-corrected):
- window: FULL (18:00 ET prior evening to 16:00 ET) or RTH (09:30-16:00 ET)
- stop distance beyond the wall: 0.10 EM or 0.25 EM
- target: 5R (the guide's example), REF (back to the prior close C), or 1R
Primary variant, named in advance: FULL window, stop 0.10 EM, target 5R (= 0.5 EM back toward the prior close).

Also reported, named in advance:
- HIGHWIN (illustration of win rate vs profit): FULL window, target 0.10 EM, stop 0.50 EM.
- PLACEBO: the primary variant with EM built from the 20-day historical volatility of daily closes instead of VXN.
- Descriptive: share of days that touch a wall, and share whose 16:00 close finishes beyond a wall.

Samples: all days, and the engine's fixed split (in-sample before 2020-03-18, out-of-sample from it). Nothing is fitted.
Pass bar: out-of-sample mean net points > 0 with Holm-corrected one-sided p < 0.05, at least 100 out-of-sample trades,
in-sample mean of the same sign.
