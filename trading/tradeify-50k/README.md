# Tradeify 50K Signals

Tools for trading NQ and MNQ by hand on a **Tradeify 50K Sim Funded** account:

- **`TradeifySignals.pine`** is a TradingView indicator. It posts the July NQ setups as signal prompts with a size, a stop and two targets, and sends alerts to your phone. Every size is checked against Tradeify's rules and your own daily limits.
- **The planner** estimates your odds of reaching payouts before the account breaches, for each size, from a TradingView trade list. It lives at `../apex-50k/planner/`. Run it with `--firm tradeify`.
- **`rules.json`** holds every Tradeify 50K funded rule the tools use, with source links, verified 2026-11-02.

The indicator places no orders and is not advice. The TradingView connector in Claude can read market data and create simple price alerts, but it cannot add a script to a chart or create an indicator alert. Pasting the script and creating its alert are done in TradingView. Read "The record" below before trading its signals.

## Why no signals were posting

- **The old signals were turned off on purpose.** On October 29–30 the session that built the risk tools found that the AI-TPS v2.4 pullback strategy lost money on 14 years of real NQ data. It turned the watcher's signals off on your Mac (`"tradeSignals": false` in `~/signal-analysis/watcher-config.json`) and hid the "AI Trend Pullback Signals" study on your chart. To bring those back, set that value to `true` on your Mac and unhide the study in TradingView.
- **The tools built since show no signals by design.** The Prop Firm Risk HUD and Risk Lines are risk displays only. The Eval Lab is a backtest with no alerts.
- **This indicator is the new way to get signals.** It draws every signal on the chart, today's and past ones, whether or not you have typed today's figures. Stale figures only add a warning to the label and the alert.

## Set up the indicator (about 5 minutes)

1. In TradingView open the Pine Editor, choose **Create new → Indicator**, press ⌘A then Delete so the editor is empty, and paste all of `TradeifySignals.pine`. Line 1 must read `//@version=6`. Save it and add it to an **MNQ1!** 5-minute chart.
2. In the indicator's settings, pick your **Plan**: Growth, Select Flex, Select Daily or Lightning. Tick **Legacy** if the account was bought before September 12, 2025.
3. Each day before trading, while flat, type in these figures from the Tradeify dashboard:
   - balance at last close;
   - the Trailing Max Drawdown floor;
   - the highest end-of-day balance so far;
   - today's realized P&L and the trades already taken (both 0 if you read them between sessions);
   - the date and time you read them.
4. Create the alert: **Alerts → Create alert**, Condition = "Tradeify 50K Signals", then **Any alert() function call**. Tick **Notify in app**, and allow TradingView notifications on your phone.
5. An alert keeps the inputs it was created with. Delete and re-create it after each daily update. An old alert stops posting prompts at the next session, and only its flat-by reminder still arrives, saying the inputs are STALE.

Use **MNQ**, not NQ. At the default $150 risk per trade, one NQ contract with the minimum 8-point stop costs about $171, so every NQ setup shows "no size". The table says so and names the limit that binds.

### What you see on the chart

- **Teal LONG / red SHORT arrow with a label** shows the size, entry, stop (SL), target 1, target 2, setup and score. Past signals look the same and are marked "(past)".
- **Orange label:** a live signal sized from stale figures. It still alerts, marked ACCOUNT FIGURES STALE, unless you pick "Draw only, no alerts" under Display.
- **Faded arrow with "no size":** the setup fired, but one contract risks more than your budget. On NQ, chart MNQ instead.
- **Grey "setup held back":** an account limit blocked it, such as the floor, the daily loss limit, your daily stop, the profit lock, the trade count or the loss streak. No alert.
- **Lines:** entry, stop and targets of the open signal, then its exits (T1, T2, stop, time, flat-by).

**Expect about 3 to 4 signals a week on MNQ 5-minute,** almost all Trend Pullback. From October 5 to November 2, 2026, TradingView's MNQ1! data gave 11. Only one reached target 2, and seven were stopped out. A lower "Minimum setup score" shows more: on 49 sessions, 55 gave 34 signals, 45 gave 52 and 40 gave 61. None of those levels has shown an edge.

To check the indicator on your chart, scroll back to these bars. Times are the start of the 5-minute signal bar in ET. All 11 were Trend Pullback, and the entry is the next bar's open.

| Date | Time | Side | Score | Entry | Stop | T1 | T2 | Outcome |
|---|---|---|---|---|---|---|---|---|
| Mon Oct 5 | 11:40 | LONG | 57 | 31240.50 | 31198.50 | 31303.25 | 31366.00 | T1, then time stop |
| Wed Oct 7 | 14:15 | LONG | 56 | 31381.25 | 31335.25 | 31451.75 | 31521.75 | stop |
| Mon Oct 12 | 11:20 | SHORT | 74 | 30891.75 | 30936.25 | 30827.25 | 30762.00 | stop |
| Mon Oct 12 | 13:30 | SHORT | 69 | 30876.50 | 30931.00 | 30795.75 | 30714.50 | time stop |
| Wed Oct 14 | 13:00 | SHORT | 57 | 30262.50 | 30320.50 | 30175.25 | 30088.00 | T2 |
| Mon Oct 19 | 13:40 | SHORT | 68 | 29766.25 | 29822.50 | 29682.75 | 29598.75 | stop |
| Wed Oct 21 | 14:00 | LONG | 71 | 30053.50 | 30033.50 | 30082.50 | 30112.00 | T1, then breakeven stop |
| Mon Oct 26 | 12:05 | LONG | 56 | 29476.75 | 29436.50 | 29538.00 | 29599.00 | stop |
| Tue Oct 27 | 13:05 | LONG | 57 | 29802.75 | 29767.25 | 29855.00 | 29907.75 | stop |
| Wed Oct 28 | 11:15 | SHORT | 68 | 29842.00 | 29873.00 | 29796.25 | 29750.25 | stop |
| Thu Oct 29 | 14:55 | SHORT | 68 | 29464.50 | 29503.25 | 29407.25 | 29349.50 | stop |

Small differences against your chart are expected, because the history TradingView loads differs slightly by plan and the indicator needs a warm-up.

### What a signal looks like

```
MNQ LONG 3 @ 21534.25 | stop 21510.00 (24.25 pts, $147.00 risk) | T1 21570.50 | T2 21606.75 | Trend Pullback 72 | floor room $2,000 | DLL room $1,250 | Tradeify Growth 50K
```

The indicator then follows the trade as a virtual position. It posts the exit: T1 (half off, stop to breakeven), T2, stop, time stop or flat-by. A reminder arrives 10 minutes before the 4:45 PM ET flat time.

### What hides or holds back a signal

Not drawn at all:
- outside 9:35 AM–3:30 PM ET, or within 20 minutes of the 4:45 PM ET flat time;
- while an earlier signal is still open, or during warm-up.

Drawn grey, with no alert:
- no room left to the drawdown floor;
- the daily loss limit (soft) or your own daily stop is hit;
- the profit lock is hit (Growth $1,000, Lightning $600 by default);
- 3 trades already taken, or 2 losses in a row.

Drawn faded, with no alert: the size works out below 1 contract.

Stale figures never hide a signal. They only add the warning.

The profit lock keeps any one day under the consistency limit. Growth allows no single day above 35% of the profit since the last payout.

## Tradeify 50K funded rules modelled

| | Growth | Select Flex | Select Daily | Lightning |
|---|---|---|---|---|
| Drawdown | $2,000 end-of-day trailing | same | same | same |
| Daily loss limit (soft) | $1,250, then $2,000 after a $53,000 close | none | $1,000 | $1,250, then $2,000 after a $53,000 close |
| Max contracts | 4 minis or 40 micros | 2, then 3 and 4 as profit reaches $1,500 and $2,000 | same as Flex | 4 minis or 40 micros |
| Consistency | 35% | none | none | 20%, 25%, then 30% |
| Payout | 5 days over $150, balance $53,000, $1,500 to $3,000 | 5 days of $150+, 50% of profit, up to $2,500 | 2× cycle profit, up to $1,250, above $52,100 | $3,000, then $2,000 new profit, $2,000 to $2,500 |

Rules shared by all four plans:
- **Drawdown floor:** it moves only at the end of the day, but it is enforced live against balance plus open P&L. Touching it intraday fails the account, even if the price comes back.
- **Lock:** the floor locks at $50,100 once an end-of-day balance reaches $52,100, or as soon as a payout is requested.
- **Flat by 4:45 PM ET**, or 12:59 PM ET on early-close days.
- **Payouts:** you receive 90%.

Four readings the help pages leave open are listed under `unverified` in `rules.json`.

## The record

The July setups were run on 49 real sessions of MNQ 5-minute data, August 24 to October 30, 2026. Twenty seeded random-entry runs used the same engine, stops, targets, gates and sizing:

| | Trades | Win rate | Mean per trade |
|---|---|---|---|
| July setups | 18 | 39% | −0.12R, or −$12.58 per micro |
| Random entries, median of 20 runs | 19.5 on average | n/a | −0.12R |

Ten of the 20 random runs did better than the setups. The 95% interval for the setups' mean is −0.64R to +0.46R, so the loss is not statistically certain. Over 14 years of real NQ data, similar setups also failed after costs (the October research).

The planner, run on those real trades on a Growth funded account over 120 trading days, gives:

| Trade list | Best chance of at least one payout | Breach before the first payout |
|---|---|---|
| July setups, real trades | 17.2%, at 5× the $100 risk | 80.8% |
| No edge (33% wins at 2:1) | 22.4%, at 2 minis | 77.6% |
| A real edge (40% wins at 2:1) | 59.5%, at 1 mini | 27.1% |

**What this means:** treat the signals as prompts to judge, not a system to follow. If you want to know whether your own trading has an edge, export your trades and run the planner on them. With an edge, smaller size gives the best payout odds.

## Run the planner

From `../apex-50k/`:

```
node planner/cli.mjs --firm tradeify --plan growth --trades list-of-trades.csv --unit micro --sweep
```

For the trade list, use the Eval Lab in **Raw trades** mode with **Exit model = Fixed R** and flat-by at 16:40. Then export **Strategy Tester → List of trades**. Your own broker or journal export works too.

How the planner reads a trade list:
- It resizes trades by their own risk (`--scale risk`, automatic when sizes vary).
- It merges scale-out legs into one position.
- It warns when trades exceed the plan cap.

Options:
- `--plan select-flex|select-daily|lightning` switches plans.
- `--legacy` uses the pre-September-12-2025 limits.
- `--from`/`--to` put several trade lists on the same calendar.
- `--help` lists everything else.

Tests: `node --test planner/test/` (96 pass).
