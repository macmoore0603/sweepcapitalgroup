# Apex 50K Eval Lab

Two tools for one goal: pass the Apex Trader Funding 50K Intraday evaluation and reach payouts, without risking money on a signal that has not proven itself.

- **`ApexEvalLab.pine`** is a TradingView strategy. It runs a signal under the exact Apex 50K Intraday rules, restarts the evaluation again and again through the chart's history, and reports how often attempts passed. Beside it, it runs a random-entry control with no edge.
- **`planner/`** is a command-line planner. It reads the trade list TradingView exports and estimates, for each contract size, the odds of passing the evaluation and then collecting payouts.

Neither tool places orders, sends alerts or gives trade advice.

## Why this exists

Earlier research on this project found no signal with an edge:

- In October, six NQ setups were tested on 14 years of 1-minute NQ data (Databento, 2010–2024) with realistic costs. They were pullback (AI-TPS v2.4), opening-range breakout, last-half-hour momentum, VWAP mean reversion, overnight-level fade and a v2.4 variant. All six failed the pre-registered bar, and none reached it even with zero costs.
- The July NQ setups were never tested on real data.

So the honest next step is to measure, not to add signals. The lab shows whether a signal beats random entries under the real rules. The planner shows how to size whatever edge you have, or don't have, to give yourself the best odds.

## Rules modelled

Verified 2026-11-01 from the Apex help center. All numbers live in `rules.json`, with the source links. The firm can change its rules at any time, so re-check before relying on them.

| | Evaluation | Performance Account |
|---|---|---|
| Profit target | +$3,000 on closed P&L | none |
| Trailing drawdown | $2,000 from the peak balance, including open profit; real time; never moves down | same |
| Threshold stops trailing | $53,000 on Rithmic/WealthCharts; keeps trailing on Tradovate | $50,100, once the peak reaches $52,100 |
| Breach | balance touches or falls below the threshold | same; the account closes |
| Max size | 6 minis or 60 micros | by tier: 2, 3, 4, 4 minis |
| Daily loss limit | none | by tier: $1,000, $1,000, $2,000, $3,000; a hit pauses the rest of the session |
| Tier from prior close | n/a | profit $0 / $1,500 / $3,000 / $6,000 |
| Time limit | 30 calendar days | none |
| Payouts | n/a | 5 days of at least $200 each, 50% consistency, balance at least $52,600, $500 minimum, per-request caps $1,500 to $3,000, at most 6 |

Two readings could not be confirmed from the pages and are listed under `unverified` in `rules.json`. One is the Level 4 boundary. The other is what the unlabeled payout-table columns mean.

## Use the lab in TradingView

1. Open the Pine Editor, choose **Create new → Strategy**, press ⌘A then Delete so the editor is empty, and paste all of `ApexEvalLab.pine`. Line 1 must read `//@version=6`. A search for `strategy(` should find exactly one declaration. If it finds two, the editor's template is still there, which causes error CE10243.
2. Save it, add it to an **MNQ1!** or **NQ1!** chart on 1 to 5 minutes, and open the Strategy Tester.
3. In Inputs, keep **Account mode = Evaluation** and set the **Data feed** to match your account. **Risk per trade** defaults to $100, which suits MNQ.
4. Set **Out-of-sample start** to a date after any period you tuned settings on.
5. Read the table at the top right. It has rows for the signal and for the random control, split in-sample and out-of-sample, with attempts, passed, breached, expired, pass rate and median days to pass.

**How to judge a signal.** It has shown something only if its **out-of-sample** pass rate clearly beats the random control's, over enough attempts to mean something. Thirty or more out-of-sample attempts is a sensible minimum. A few attempts are anecdotes. If the signal does not beat random, trading it live is paying evaluation fees for variance.

Other signal sources:
- **External indicator** tests any indicator's plot: a value above 0 means long, below 0 means short.
- **Random control only** trades the random entries in the Strategy Tester itself, which cross-checks the lab's ledger against TradingView's fills.

Limits:
- History depth depends on your TradingView plan.
- The order of high and low inside a bar is unknown, so the lab assumes the worst case: the favorable extreme first, then the adverse one.
- Orders fill at the next bar's open, with one tick of slippage.
- Holiday early closes are not scheduled.

To check the script compiles from a terminal, run this from this folder:

```
node tools/compile-check.mjs ApexEvalLab.pine
```

## Use the planner

You need Node 22 or newer. Everything runs from this folder, and nothing is installed.

**From your own trades (recommended).** In the Strategy Tester, open **List of trades** and export it to CSV. Then run:

```
node planner/cli.mjs --trades list-of-trades.csv --sweep --mode both --fee 0
```

It bootstraps whole trading sessions from your history, keeping the real number of trades per day and their order. It uses each trade's run-up and drawdown to model the intraday trailing threshold. For each size from 1 to 6 minis it prints:
- P(pass), P(breach) and P(expire);
- days to pass;
- payout odds in the Performance Account;
- a replay of your actual trade order.

Pass your evaluation price with `--fee` to rank sizes by payout per dollar of fees.

**From assumed stats.** For example:

```
node planner/cli.mjs --win 0.40 --rr 2 --risk 100 --tpd 2 --cost 1.34 --sweep --mode both
```

Each trade's 1R varies by ±50% by default (`--r-spread`), the way stops of different widths do at a fixed size. Use `--r-spread 0` for exact ±1R trades. Use `--zero-edge` to see the no-edge baseline for the same settings. Run `--help` for every option.

### What the numbers say (seed 1, 20,000 attempts)

**With no edge** (50% wins at 1:1, $200 per mini per R, 2 trades a day, no costs), the best any size reaches is about **1 pass in 5 attempts**:

| Minis | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| P(pass) | 2.6% | 19.3% | 20.4% | 20.3% | 18.2% | 18.5% |

That is well below the 40% a plain ±$2,000/$3,000 coin flip would suggest. The trailing threshold rises on open profit and then catches the pullback.

**With a real edge** (40% wins at 2:1, $100 per mini per R, $1.34 cost, about +$19 per trade per mini), the results look like this:

| Minis | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| P(pass) | 2.3% | 32.8% | 43.9% | 39.8% | 36.4% | 33.6% |

At 1 mini, most attempts run out of time. At 6, too many breach. The best size is in the middle, and in this example about 26% of attempts both pass and collect a payout within 120 trading days. Your own CSV will give your own curve.

## Tests

```
node --test planner/test/
```

There are 61 tests, covering:
- the ledger rules at their exact boundaries;
- the trailing and threshold-stop behavior;
- Performance Account tiers, the daily loss limit and payout gating;
- Monte Carlo checks against closed-form results;
- TradingView CSV variants;
- a sync test that fails if the Pine rules block and `rules.json` disagree.

## Files

| File | Purpose |
|---|---|
| `rules.json` | Apex 50K Intraday rule numbers, sources, verification date |
| `ApexEvalLab.pine` | TradingView strategy: the lab |
| `tools/compile-check.mjs` | Compile a .pine file with TradingView's public checker |
| `planner/ledger.mjs` | Evaluation and Performance Account rules as pure functions |
| `planner/sim.mjs` | Monte Carlo, bootstrap and historical replay |
| `planner/tv-csv.mjs` | TradingView "List of trades" CSV parser |
| `planner/time.mjs` | New York session and calendar helpers |
| `planner/cli.mjs` | Command-line interface |
| `planner/test/` | Tests and CSV fixtures |
