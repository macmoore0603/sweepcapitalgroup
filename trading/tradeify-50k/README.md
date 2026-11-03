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
- **Your alerts, as of November 2.** These were read through the TradingView connector:
  - The only active alert is on the old AI Trend Pullback strategy (MNQ1!, 5-minute). It was created October 20 and has never fired.
  - The 15-minute v2.4 alert has stopped after a script error. TradingView does not restart such an alert by itself.
  - No alert exists yet for this indicator.
  - Phone notifications work: the October 16 test alert arrived.

## Set up the indicator (about 5 minutes)

1. In TradingView open the Pine Editor, choose **Create new → Indicator**, press ⌘A then Delete so the editor is empty, and paste all of `TradeifySignals.pine`. Line 1 must read `//@version=6`. Save it and add it to an **MNQ1!** 5-minute chart. Keep the chart's session on **Electronic trading hours** (Settings → Symbol → Session), which is the default. On Regular trading hours the table warns you, because the flat-by exit and the overnight levels then work differently.
2. In the indicator's settings, pick your **Plan**: Growth, Select Flex, Select Daily or Lightning. Tick **Legacy** if the account was bought before September 12, 2025.
3. Each day before trading, while flat, type in these figures from the Tradeify dashboard:
   - balance at last close;
   - the Trailing Max Drawdown floor;
   - the highest end-of-day balance so far;
   - today's realized P&L and the trades already taken (both 0 if you read them between sessions);
   - the date and time you read them;
   - on Growth, the four **Payout progress** inputs (see below). The profit lock and the payout rows depend on them.
4. Create the alert: **Alerts → Create alert**, Condition = "Tradeify 50K Signals", then **Any alert() function call**. Tick **Notify in app**, and allow TradingView notifications on your phone.
   - **This needs a paid TradingView plan.** An alert on an indicator counts as a "technical alert". The free Basic plan allows none: it gets only 3 price alerts. Essential allows 20 technical alerts, Plus 100 and Premium 400.
   - If a renewal failed and the account dropped to Basic, TradingView stops every active alert. They can only be restarted within the new plan's limits.
   - Basic alerts last up to 1 month, Essential and Plus up to 2 months.
5. An alert keeps the inputs it was created with. Delete and re-create it after each daily update. An old alert stops posting prompts at the next session, and only its flat-by reminder still arrives, saying the inputs are STALE.

Use **MNQ**, not NQ. At the default $150 risk per trade, one NQ contract with the minimum 8-point stop costs about $171, so every NQ setup shows "no size". The table says so and names the limit that binds.

### What you see on the chart

- **Teal LONG / red SHORT arrow with a label** shows the size, entry, stop (SL), target 1, target 2, setup and score. Past signals look the same and are marked "(past)".
- **Orange label:** a live signal sized from stale figures. It still alerts, marked ACCOUNT FIGURES STALE, unless you pick "Draw only, no alerts" under Display.
- **Faded arrow with "no size":** the setup fired, but one contract risks more than your budget. On NQ, chart MNQ instead.
- **Grey "setup held back":** an account limit blocked it, such as the floor, the daily loss limit, your daily stop, the profit lock, the trade count or the loss streak. No alert.
- **Lines:** entry, stop and targets of the open signal, then its exits (T1, T2, stop, time, flat-by).

**Expect about 2 to 3 signals a week on MNQ 5-minute,** almost all Trend Pullback. From October 5 to November 2, 2026, TradingView's MNQ1! data gave 11, and seven were stopped out.

A lower "Minimum setup score" shows more. These counts take signals one at a time, as the chart draws them:

| Minimum score | 49 sessions, Aug 24 to Oct 30 | Oct 5 to Nov 2 |
|---|---|---|
| 55 | 22 | 11 |
| 45 | about 25 | 11 |
| 40 | about 30 | 12 |

None of those levels has shown an edge.

To check the indicator on your chart, scroll back to these bars. All 11 were Trend Pullback. In the table:
- **Time** is the start of the 5-minute signal bar, in ET.
- **Label @** is the signal bar's close, the price the chart label and the alert show.
- **Fill** is the virtual entry: the next bar's open plus 1 tick against you.
- **Outcome** is what the chart shows at the default inputs.

| Date | Time | Side | Score | Label @ | Fill | Stop | T1 | T2 | Outcome |
|---|---|---|---|---|---|---|---|---|---|
| Mon Oct 5 | 11:40 | LONG | 57 | 31240.50 | 31240.50 | 31198.50 | 31303.25 | 31366.00 | T1 (1 MNQ exits whole) |
| Wed Oct 7 | 14:15 | LONG | 56 | 31382.00 | 31381.25 | 31335.25 | 31451.75 | 31521.75 | stop |
| Mon Oct 12 | 11:20 | SHORT | 74 | 30892.50 | 30891.75 | 30936.25 | 30827.25 | 30762.00 | stop |
| Mon Oct 12 | 13:30 | SHORT | 69 | 30876.75 | 30876.50 | 30931.00 | 30795.75 | 30714.50 | time stop |
| Wed Oct 14 | 13:00 | SHORT | 57 | 30262.25 | 30262.50 | 30320.50 | 30175.25 | 30088.00 | T1 (1 MNQ exits whole) |
| Mon Oct 19 | 13:40 | SHORT | 68 | 29766.50 | 29766.25 | 29822.50 | 29682.75 | 29598.75 | stop |
| Wed Oct 21 | 14:00 | LONG | 71 | 30053.25 | 30053.50 | 30033.50 | 30082.50 | 30112.00 | T1, then breakeven stop |
| Mon Oct 26 | 12:05 | LONG | 56 | 29477.25 | 29476.75 | 29436.50 | 29538.00 | 29599.00 | stop |
| Tue Oct 27 | 13:05 | LONG | 57 | 29802.50 | 29802.75 | 29767.25 | 29855.00 | 29907.75 | stop |
| Wed Oct 28 | 11:15 | SHORT | 68 | 29842.25 | 29842.00 | 29873.00 | 29796.25 | 29750.25 | stop |
| Thu Oct 29 | 14:55 | SHORT | 68 | 29464.75 | 29464.50 | 29503.25 | 29407.25 | 29349.50 | stop |

**Size changes some outcomes.** At the default $150 risk, Oct 5 and Oct 14 size to 1 MNQ, and a single contract exits whole at target 1. With 2 or more contracts, half goes off at T1 and the rest runs: Oct 5 then ends at the time stop, and Oct 14 reaches T2.

**Your typed figures change the table.** Past signals are sized and gated with the figures you type, and daily limits apply to past days too. The table needs a budget of at least $118 per trade, both as risk per trade and as the share of your room to the floor. That means at least $1,190 of room at the default 10% share. Oct 14 costs $118.00 per contract, and Oct 12 13:30 costs $110.00 after that morning's $90 loss.

With a smaller budget, some rows show "no size" and start no virtual trade, so a later setup can appear instead. For example, at $100 risk:
- Oct 12 13:30, Oct 14 and Oct 19 show "no size";
- a SHORT Trend Pullback 63 appears at Oct 12 13:55.

**Your TradingView plan limits how far back you can see.** The indicator needs 200 bars of warm-up, and intraday history depends on the plan:

| Plan | Intraday bars | On November 2 |
|---|---|---|
| Basic | 5,000, about 18 trading days of 5-minute MNQ | the chart starts at Oct 7 14:00 ET and draws from about Oct 8 07:40 ET, so the Oct 5 and Oct 7 rows are missing |
| Essential, Plus | 10,000 | all 11 rows show until about mid-November |

Each day the history window moves forward one trading day, so on Basic the Oct 12 rows drop off around Nov 5. Bar Replay also works for checking.

### What a signal looks like

```
MNQ LONG 3 @ 21534.25 | stop 21510.00 (24.25 pts, $147.00 risk) | T1 21570.50 | T2 21606.75 | Trend Pullback 72 | floor room $2,000 | DLL room $1,250 | Tradeify Growth 50K
```

The indicator then follows the trade as a virtual position. It posts the exit: T1 (half off, stop to breakeven; a single contract exits whole at T1), T2, stop, time stop or flat-by. A reminder arrives 10 minutes before the 4:45 PM ET flat time.

On early-close days the flat-by is 12:59 PM ET, with the reminder and the exit moved earlier to match. The indicator only knows the dates in its **Early-close dates** input: November 26 and 27 and December 24, 2026. Add later dates from the CME holiday calendar. If the session still ends before a prompt fills, the indicator sends a CANCEL alert.

### What hides or holds back a signal

Not drawn at all:
- outside 9:35 AM–3:30 PM ET, or within 20 minutes of the flat time (4:45 PM ET, or 12:59 PM ET on the listed early-close dates);
- while an earlier signal is still open, or during warm-up.

Drawn grey, with no alert:
- no room left to the drawdown floor;
- the daily loss limit (soft) or your own daily stop is hit;
- the daily profit lock is hit (on Auto: Growth $990 before the first payout, then set by your payout cycle; Lightning $600);
- 3 trades already taken, or 2 losses in a row.

Drawn faded, with no alert: the size works out below 1 contract.

Stale figures never hide a signal. They only add the warning.

The profit lock keeps any one day under the consistency limit. Growth allows no single day above 35% of the profit since the last payout.

On Auto, the Growth lock is worked out from your payout cycle:
- Every Growth payout needs a balance of at least $53,000. So at any request, the profit since the last payout is at least $53,000 minus the cycle start.
- The lock is 95% of 35% of that, rounded down to $10. A day up to the lock stays within 35% at any request.
- It is $990 before the first payout, and $490 after a $1,500 payout from $53,000.
- It never goes below $300. That floor applies once the cycle start is above about $52,080, and it is not a guarantee: losing days can still push such a day over 35% and delay the payout.
- It reads **Balance at the start of this payout cycle** and **Payouts taken so far**. Update both after each payout. If they do not fit together, the lock uses the tightest value and the table says so.

### Payout progress (Growth)

Type these four inputs with the daily figures, as of the same time:
- **Balance at the start of this payout cycle**: $50,000 before the first payout, then the balance just after the last payout left the account.
- **Qualifying days since the last payout**: closed sessions with a day profit above $150.
- **Largest profitable day since the last payout.**
- **Payouts taken so far**: approved payouts only.

A payout request locks the floor at $50,100 at once. The money only leaves on approval, which can take up to 72 hours. Until then, keep the balance at $53,000 or more, or the request is denied. Keep the inputs as they are until the payout is approved.

The table then shows four rows, as if the day ended now:

| Row | Shows |
|---|---|
| Payout days | qualifying days, n of 5, and whether today would qualify |
| Payout balance | the balance against $53,000, and how much is missing or to spare |
| Consistency 35% | the largest day as a share of the cycle profit, and the profit still needed if it is over 35% |
| Next payout | the cap for the next payout ($1,500 / $2,000 / $2,500, then $3,000), the most you could request, what you receive at 90%, and the room left above the floor |

A few things change how the rows read:
- **Virtual trades are included.** The figures include the session's virtual trades, marked "incl. virtual". These are prompts you may not have taken.
- **Thin room after a payout.** If the most you could request would leave less than one daily loss limit ($1,250) above the floor, the Next payout row turns orange. It then also shows the amount that keeps $1,250.
- **Stale figures.** With stale or future figures, all four rows turn orange and say STALE.
- **Inputs that cannot be true together.** These turn Consistency and Next payout red, with the reason:
  - a cycle start other than $50,000 with no payouts;
  - a cycle start at or below $50,100 after a payout;
  - a cycle start above the highest end-of-day balance;
  - qualifying days with a largest day of $150 or less;
  - a balance above the cycle start with a largest day of 0.

The rows request nothing. They do not check the 10-second rule, KYC or Rise.

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
- **Flat by 4:45 PM ET**, or 12:59 PM ET on early-close days. The indicator applies the early time on the dates in its "Early-close dates" input.
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

### Start from your account now

By default the planner simulates a fresh $50,000 account. To get odds for the funded account you hold, type its dashboard figures:

```
node planner/cli.mjs --firm tradeify --plan growth --trades list-of-trades.csv --unit micro --sweep \
  --balance 51800 --floor 49800 --high-eod 51800 --qual-days 3 --cycle-max-day 700
```

| Flag | What to type | Default |
|---|---|---|
| `--balance` | balance at the last close | required |
| `--floor` | the Trailing Max Drawdown floor | required |
| `--high-eod` | the highest end-of-day balance so far | the larger of balance and $50,000 |
| `--cycle-start` | $50,000 before the first payout, then the balance right after the last payout | $50,000 |
| `--qual-days` | days above $150 since the last payout | 0 |
| `--cycle-max-day` | largest profitable day since the last payout | required once the cycle is in profit |
| `--payouts-taken` | approved payouts so far | 0 |

Quote dollar values or leave out the `$`. In bash an unquoted `$49,000` arrives as `9,000`, and the planner rejects it.

What the planner does with them:
- **The Start line** shows your room to the floor and the progress on each payout condition. It says whether you could request now, and if not, what blocks it.
- **The table** then counts only payouts made from now on.
- **Impossible states are rejected with a reason.** For example: a floor that cannot exist, or qualifying days with a largest day of $150 or less.

The example above runs the July setups' real trades from a $51,800 balance. The best size is 5 times the as-traded risk: 48% reach the next payout, but 51% breach first. The setups lose $12.58 per trade per micro, so the planner says it plainly: "payouts here are luck, not edge".

Not modelled:
- The planner pays out at the close of the request day. Tradeify pays on approval, which can take up to 72 hours. Until approval, the balance must hold $53,000 or the request is denied. So time between payouts is slightly optimistic, and a denial never happens in the simulation.
- The most you can request, the cap or the balance minus $50,100, is read from Tradeify's worked example. The help pages give no formula for it.

Tests: `node --test planner/test/` (118 pass). One of them checks that the rule constants in `TradeifySignals.pine` match `rules.json`.
