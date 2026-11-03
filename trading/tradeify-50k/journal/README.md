# Prediction journal

Write each chart call down **before** the move, paper or live. The journal then grades every call against real bars, the same way every time, so you learn whether your read has an edge before you risk money. Needs Node 22, nothing else.

## 1. Write the call down, before the move

```
node journal.mjs add --calls calls.csv --side long \
  --entry 28250.25 --stop 28230.25 --target 28290.25 --note "pullback to VWAP, 2nd test"
```

- `--time "2026-11-04 10:35"` (New York time, 24-hour clock) is the minute you make the call. Leave it out to use the current minute.
- A time before the current minute is refused, because a call written after the move is hindsight. To record a past call anyway, add `--backfill`: the score lists it but leaves it out of every figure.
- Every call gets an `[added YYYY-MM-DD HH:MM ET]` stamp at the end of its note, so the score can tell when it was written. Rows you type by hand have no stamp, and the score says how many.
- Optional: `--size 1`, `--symbol MNQ` (or `NQ`), `--mode paper` (or `live`).
- It refuses a stop or target on the wrong side of the entry, a size that is not 1 to 40 MNQ (1 to 4 NQ), an unknown symbol, a price off the 0.25 tick, and a time when no trade may be open (16:45 to 18:00 ET, weekends). It warns for a call after 16:39, which has no 5-minute bar left to fill on (after 16:43, no 1-minute bar either).
- Split targets: log T1 and T2 as two rows with the same time, side, entry and stop. The score counts them as one idea.

`calls.example.csv` shows the file: `id,time_et,symbol,side,entry,stop,target,size,mode,note`.

## 2. Grade your calls

```
node journal.mjs score --calls calls.csv --bars mnq_1m.csv
```

- Bars: 1-minute bars are best. 5-minute bars work, but the rest of the bar a call was written in is not graded, so a fill in those minutes is missed (the report lists those calls). Use CSV `timestamp,open,high,low,close[,volume]` (ISO time with offset, or unix seconds), or the TradingView connector's JSON saved to a file.
- **Each timestamp must be the time the bar opens**, as TradingView exports it. A file stamped at bar close (some platforms, such as NinjaTrader, do this) would let a call see a bar that ended before it, so a file with bars stamped in the 17:00 to 18:00 ET break is refused.
- **Use bars of the contract you trade.** `MNQ1!` is not back-adjusted: in roll week it can be 100 to 250 points away from the next contract (for example `MNQZ2026`). Use that contract's own bars, or `MNQ1!` only outside roll week. A call whose entry is far from every price in its fill window gets a hint in its detail.
- NQ calls are graded on MNQ bars too: same index.
- The connector returns at most 5000 bars per call (8000 with `format=columns`, about 5.8 days of 1-minute bars). For a longer stretch, page back with `date_to` (its `next_date_to`), save each page, and give `--bars` once per file, oldest first. Where files overlap, the later file's bar is used.
- The newest bar is always left out, because it may still have been forming when the file was saved. The report says which bar was left out.
- `--room 199`: your dollars of room to the drawdown floor before the first call. `--cost MNQ=0.5,NQ=1.5`: round-trip commission per contract, per symbol (a symbol left out keeps its default; a single number such as `--cost 0` applies to both). The report prints the cost each symbol was charged. `--json` for machine-readable output.

## The rules (also printed at the top of every score)

1. **Start:** a call is live from the first bar that opens after the minute it was written. Bars that had already started were partly seen, so they are not used.
2. **Fill:** it fills when, within 30 minutes, a bar touches the entry or price jumps over the entry between bars (last close on one side, next open on the other). A jump fills at the worse of the entry and that open. If not, it is NOT FILLED and left out of the stats. If price jumped over the entry and the stop together, it counts as filled at the entry and stopped at that open.
3. **Exit:** a bar touching the stop is a STOP (at the stop, or at the open if the bar gapped past it). A bar touching the target is a TARGET. Stop and target in the same bar count as a **STOP** (unless the bar opened past the target): the order inside a bar is unknown, so the journal assumes the worse. On the fill bar a stop touch counts; a target touch counts only if price was already moving toward the target.
4. **Flat:** still open at 16:45 ET, it exits FLAT at the close of the last bar that ends by 16:45. A session runs 18:00 to 17:00 ET, so a call at or after 18:00 belongs to the next day. If the bars end first, it is OPEN and left out of the stats.
5. **Money:** $ = points x $2 (MNQ) or $20 (NQ) x size, minus cost x size. R = $ / the $ at risk (entry-to-stop points x point value x size), so commissions count against R. R before commissions is shown too.
6. **Room:** every bar is walked in time order from `--room`, which never grows past $2,000 because the floor trails. At each bar the walk takes the room left after closed trades plus the open P&L of every open call at that bar's worst price, so calls open together add up. A closed trade is credited at its exit bar. The walk stops at the first breach.
7. **Counting:** rows with the same time, side, entry and stop are one idea, at their risk-weighted R. The stats and the 30-call minimum count ideas. A backfilled call (stamped as added after its time) is listed but left out of every figure.

## How the fills lean

- No slippage: fills are at exact prices.
- **A touch counts as a fill.** This is optimistic for a resting limit: at the exact high or low you may not be filled. The report marks every target that was only touched, not traded through.
- These two are why real results will be somewhat worse than the score.

## Reading the result

- **1R** is what you planned to lose, plus commissions. +1.5R means you won one and a half times your risk after costs.
- **Average R interval** (95%, bootstrap, after commissions): where your true average probably is. Above 0 means an edge, before slippage. If it includes 0, no edge is shown yet.
- **Fewer than 30 graded ideas is too few to judge.** Keep writing them down.
- **Room check:** whether these calls, at these sizes, would have breached the account. If it says ACCOUNT BREACHED, the size is too big for the room you have, and the verdict says so too. It also lists calls that were open together, and a combined size above 40 MNQ / 4 NQ.

## Pre-trade check with Claude

Before any call, paper or live, send Claude the idea or a chart screenshot. Claude answers in six steps:

1. **Market:** trend, key levels and any news due, from live MNQ1! data.
2. **Setup:** what the idea is, and what would cancel it.
3. **Plan:** entry, stop and target, on the 0.25 tick.
4. **Risk:** size, the $ loss at the stop, and the typical adverse move for this kind of trade, compared with your room to the floor. If the stop or the typical move does not fit the room, the answer is SKIP.
5. **Alerts:** TradingView price alerts at the stop and the target.
6. **Call:** TAKE IT, WATCHLIST or SKIP, with the 3 biggest reasons it could fail.

Every TAKE IT and every WATCHLIST is recorded with `add` the minute it is made. The journal then grades the check itself: whether TAKE IT calls beat the others. A confident-sounding check proves nothing until the journal shows it. Claude does not place orders.

Not modelled: early-close days. Tradeify's flat-by is then 12:59 ET, but the journal still uses 16:45, so a trade exits at the market's last bar.

Tests: `node --test test/`
