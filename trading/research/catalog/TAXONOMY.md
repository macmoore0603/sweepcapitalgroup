# TAXONOMY: rule families for the 979 discovered NQ strategies

48 families (F01-F48) and 6 X keys. Each record gets exactly one key. `~n` = draft member count from a first pass over all 979 records (777 in families, 202 in X keys); the mapping step decides with the full rules.

## Shared vocabulary
- Times are ET. RTH = 09:30-16:00; the Globex day starts 18:00. No bar after 16:15 may be used; intraday trades are flat by 16:10 at the latest (default `flat` = 15:59). Skip days with fewer than 370 RTH 1m bars.
- Bars: NSX 1m/5m OHLC, no volume. pts = index points (tick 0.25). Fills on 1m bars: a signal on a bar close fills at the next bar open; a stop order fills at its level (bar open if gapped through); a limit fills only if traded through; stop and target in the same bar = stop first.
- atr = ATR(14) on the signal bars. datr = 14-day ATR of RTH daily bars. R = entry-to-stop distance.
- swing(k) = bar whose high/low is the extreme of k bars each side, usable k bars later. sweep(L) = price trades beyond level L, then a bar closes back inside. MSS = a bar closes beyond the last swing against the prior move. FVG = 3 bars with bar3.low > bar1.high (bullish) or bar3.high < bar1.low (bearish).
- P = TW-VWAP proxy = running mean of typical price (H+L+C)/3 from the anchor time. It is NOT VWAP (no volume). Every member that uses P carries `vwap_proxy=1`.

## Common parameters (valid in every family; write only what the source states)
- `res` {1m,5m,15m,30m,60m,1d}; `dir` {both,long,short} [both]; `win` [t0,t1] entry window; `flat` exit time [15:59]; `hold` max bars or minutes [none]; `max_tr` entries per day [1].
- `stop`: none | pts:x | pct:x | atr:k | datr:k | rng:f (fraction of the setup range measured from the entry edge; 1 = opposite edge, 0.5 = midpoint) | bar (far extreme of the signal bar, pattern or sweep) | swing | level:name.
- `tgt`: none | R:k | pts:x | pct:x | atr:k | datr:k | rng:f | level:name. Also `be` [none] (stop to entry at +kR), `trail` [none] (atr:k, bars:n), `partial` [none].
- `filt` (list): dow | trend (close vs sma_d(n) or ema(tf,n)) | gap (direction, min, max) | rngw (setup-range width min/max, x datr or % of price) | adx(n)>x | twap side | prev_day up/down | setup_day (NR7, NR4, inside ...) | cal (opex, fomc ...).
- Flags: `vwap_proxy`, `vol_dropped`, `rescaled` (ES/SPY/CFD points or pips converted to % of price or x ATR), `defaults_used` (list), `variants` (extra parameter sets of the same family), `x_sub`.
- Notation below: `name {allowed values} [default] (other published values)`. The default is the most commonly published value.

## Routing (choose by entry trigger first, then by level class)
1. Data we lack -> an X key (end of file). Volume used only as a side filter -> drop it (`vol_dropped`). VWAP -> P.
2. Range from 09:30: up to 45 min with stop entry F01, with close entry F02; 60+ min F05; retest entry F03; fade F04. Any other clock-window range: break F06, sweep F07. Prior-day or n-day extreme: break F09, reclaim F10. Limit at a level F11; revert to an anchor price F12. Pivots F13; fixed grids F14. Rolling swing or n-bar level: break F15, sweep F16.
3. ICT chain: entry is the first FVG in a window -> F17; sweep + MSS + FVG/OB retrace -> F18; FVG inversion -> F19; zone or order-block retest without the chain -> F20; sweep with a plain close-back -> F07, F10 or F16 by level; retracement % of a leg -> F21.
4. Direction from a same-day return: the opening gap, traded at the open F25; any other reference window with entry before 12:00 F08, with entry at or after 12:00 F23; noise band F24. No same-day signal: clock F26, calendar F27, release day F28.
5. Indicators: state flip F29-F31; pullback F32; several indicators + bracket F33; fades F34-F35; band breakout F36; open +/- k x range F37. P as the entry reference -> F38-F40 (P as a side filter stays in the entry's family).
6. Bar patterns F41-F43; value area F44; daily bars F45-F47; another daily series F48.
7. A source that only names the method -> that family's defaults. Several rules in one record -> the first fully specified one (same-family extras go in `variants`). Rules on sub-minute bars -> X_TICK unless a 1m-or-slower form is given.

## Families

### F01 ORB_STOP: Opening-range breakout, stop entry (~27)
- Def: RH/RL = high/low of or_min minutes from 09:30. Then OCO stop orders at RH+off / RL-off; the first one touched inside win trades (fill at the level). Stop = opposite edge, no target, exit at flat.
- Params: or_min 1..45 [15]; off pts [0.25]; hold_min [0] (ACD: price must stay beyond the level N min; off = A value); reentry 0/1 [0]; win [or_end, flat]; stop [rng:1] (rng:0.5, datr:k, pts); tgt [none] (R:k, rng:f, pts); filt: first_bar_dir, gap dir, rngw, trend, dow, setup_day.
- Res: 1m (range and fills). Data: price_bars.

### F02 ORB_CLOSE: Opening-range breakout, close-confirmed (~39)
- Def: Same range as F01. The first sig_res bar in win that closes beyond RH/RL by >= buf -> enter at the next open. Optional confirm: fvg (the 1m breakout bar is the middle of an FVG), closes:n (n consecutive closes outside), body:k (displacement body >= k*atr).
- Params: or_min 1..45 [15]; sig_res {1m,5m,15m} [5m]; buf pts|atr:k [0]; confirm {none,fvg,closes:n,body:k} [none]; per_dir 0/1 [0] (one long and one short attempt); win [or_end, flat]; stop [rng:1] (rng:0.5, atr:k, pts); tgt [R:2] (none, R:k, rng:0.5, atr:k); filt: twap side, trend, gap>datr, rngw, dow, prev_day.
- Res: 5m signals (1m, 15m), 1m fills. Data: price_bars.

### F03 OR_RETEST: Opening-range / IB break, then retest entry (~14)
- Def: Range = or_min minutes from 09:30 (5-90). A close beyond an edge arms that side. Enter on the pullback: retest_close (a later bar touches the broken edge and closes back outside -> next open), limit_edge, limit_in:f (limit f of the range back inside; 0.5 = midpoint), wick (wick re-enters 10-95% of the range, body stays outside), rebreak (close back inside, then enter the second break).
- Params: or_min [15]; mode [retest_close]; need_break 0/1 [1]; retest_bars [25]; sig_res [5m]; win [or_end, 12:00]; stop [rng:0.5] (rng:0.3, atr:1.2); tgt [R:2] (R:1.5, R:1.75).
- Res: 5m signals, 1m fills. Data: price_bars.

### F04 OR_FADE: Opening-range / IB failed-break fade (~10)
- Def: Range = or_min minutes from 09:30 (5-60). Fade a failed excursion: close_back (price trades beyond an edge, then a bar closes back inside -> next open), reject_bar (a bar closes beyond the edge but against the break), touch (limit at the edge on its first touch), opp_break (after one edge is swept, stop entry through the other edge). Stop beyond the excursion extreme; target = range midpoint.
- Params: or_min [15]; mode [close_back]; buf pts [1]; win [10:00, 12:00]; stop [bar]; tgt [rng:0.5] (rng:1 = opposite edge, level:P, R:k); hold [none] (35 min).
- Res: 1m or 5m. Data: price_bars.

### F05 IB_BREAK: Initial-balance breakout (first 60-180 min) (~21)
- Def: IBH/IBL = high/low of 09:30 to 09:30+ib_min. From the IB end: OCO stops 1 tick beyond (entry=stop), or the first bar close beyond -> next open (entry=close); no entry after win ends. Stop = opposite IB edge; exit at flat, or target = f x IB range beyond the edge.
- Params: ib_min 60..180 [60]; entry {stop,close} [stop]; win [ib_end, 13:30]; stop [rng:1] (rng:0.5, pts:100, datr:0.5); tgt [none] (rng:1, rng:1.5, pts:200, pivot levels); filt: gap up + close>sma_d(20), twap side, ema cross, setup_day (NR7, 3-day RSI of 1-day change < 30).
- Res: 1m (5m/15m/30m bars for close entry). Data: price_bars.

### F06 SESS_BREAK: Session-window range breakout (~21)
- Def: Range = high/low of a clock window other than the 09:30 opening window (overnight 18:00-09:30, Asia, London 03:00-09:00, pre-market, one fixed-time candle). In win: close (first bar closing beyond an edge -> next open), stop (resting stop at the edge), or retest (after the break, first pullback, then a close above the prior bar's high). Stop = opposite edge; exit at flat.
- Params: rwin [18:00, 09:30]; entry {close,stop,retest} [close]; sig_res [5m]; buf [0]; win [09:30, 16:00]; stop [rng:1] (bar, atr:1.5, pts:25); tgt [none] (R:2, R:3); filt: London-vs-Asia pattern, StochRSI pullback, trend.
- Res: 5m signals (1m, 15m), 1m fills. Data: price_bars.

### F07 SESS_SWEEP: Session-window range sweep and reverse (~22)
- Def: Range = a clock window (Asia 20:00-00:00, London, overnight, 08:00-09:30, lunch 12:00-13:30, the previous hour, or one 15m/1h/4h candle). In win price trades beyond one edge by >= breach, then the trigger: close_back (a bar closes back inside), inside:n (n closes inside), mss, or now (market on the sweep, bias-filtered) -> enter against the sweep. Stop beyond the sweep extreme; target = opposite edge.
- Params: rwin [20:00, 00:00]; win [02:00, 05:00] (NY 09:30-11:00); breach pts [0.25] (10, atr:0.3); trigger [close_back]; one_side 0/1 [1]; stop [bar]; tgt [rng:1] (rng:0.5, R:2, level: hour or midnight open); filt: midnight-open side, daily bias.
- Res: 5m or 15m signals (1m), 1m fills. Data: price_bars.

### F08 OPEN_DIR: Opening-window direction (~26)
- Def: Direction = sign(close - open) of a just-completed reference window (first RTH 5m candle; first 15/30/45 min; open to a morning check time; 18:00-19:00; London; pre-open). Enter at t_in < 12:00 with it (follow) or against it (fade); skip dojis. Signal variants: loc (close in the top/bottom quarter of the window range), drive (never retraced through the open), ohl (open = low/high). Stop = the window's far extreme; target 10R; else exit at flat.
- Params: sig [09:30, 09:35]; t_in [sig end]; mode {follow,fade} [follow]; sigtype {sign,loc,drive,ohl} [sign]; min_move [>0] (0.5*atr, 0.6%, 40 pt range); stop [bar] (datr:0.05, atr:1.5 on 1h, pts, none); tgt [R:10] (none, R:2, pts, 50% retrace); reverse 0/1 [0]; filt: sma_d(200), dow.
- Res: 5m (1m, 15m, 60m reference windows), 1m fills. Data: price_bars.

### F09 PD_BREAK: Prior-day extreme stop breakout (~20)
- Def: Level = prior RTH day's high/low (or n-day high/low, or prior open/close). A stop order at level +/- off enters with the break; an optional daily setup must hold on the setup day and may fix the direction. Stop = setup day's opposite extreme; exit at the close.
- Params: n [1] (5); setup {none,NR7,NR4,inside,ID_NR4,out_in,LHLL,smash,hidden_smash,tail,expansion,gap_unfilled,pullback123,hv_ratio,weekly_factor} [none]; off [0.25]; valid_days [1]; stop [level:setup_opp] (level:today_open, pts, datr); exit {close,first_profit_close,first_profit_open,days:n} [close]; tgt [none].
- Res: 1m fills, daily levels. Data: price_bars.

### F10 PD_RECLAIM: Prior-day extreme failed-break reclaim (~11)
- Def: Level = prior day's low/high (n=1) or n-day low/high (n=20). Price violates it by an opening gap or intraday by >= breach, then comes back: stop order at the level (buy stop at the prior low after trading under it), or a close back through -> next open. Optional setup: 80-20 bar, prior extreme >= m sessions old, ADX>30, box-breakout day, first 15m bar tags the level. Stop = today's extreme at fill; exit at the close.
- Params: n [1]; violate {gap,intraday,either} [either]; breach pts [1.25]; entry {stop,close_back} [stop]; setup [none]; stop [level:day_extreme]; tgt [none] (R:k, pts); exit [close] (trail bars:2).
- Res: 1m fills, daily levels (5m/15m for close_back). Data: price_bars.

### F11 LEVEL_LIMIT: Limit entry at a reference level (~14)
- Def: Level fixed before entry: prior RTH low/high, overnight or Asia high/low, pre-market edge, opening-range high, a session/hour open, the price at a fixed time. Resting limit at the level on its first touch in win (buy from above, sell from below); confirm=reject waits for a rejection bar (wick through, close back) and enters at its close.
- Params: level {pdl,pdh,onh,onl,asia_l,asia_h,pm_h,pm_l,orh,open@T,price@T} [pdh+pdl]; win [09:30, 10:30]; confirm {none,reject} [none]; stop [datr:0.25] (rng:0.8 of prior RTH range, rng:1.5 of Asia range, pts:15-20); tgt [R:1] (rng:0.1, rng:0.3, pts); flat [15:59] (08:00/08:25 for overnight); filt: open inside prior range, close>sma_d(20), prev_day down.
- Res: 1m. Data: price_bars.

### F12 ANCHOR_REVERT: Reversion to a session anchor price (~15)
- Def: Anchor A = price at a clock time (00:00 open, 18:00 open, 08:00 open, hour open, RTH-open candle, weekly open). When price is >= d away from A in win, trade toward A: time (enter at t_in), touch (limit at A +/- d), bos (a close beyond the last swing toward A), or disp (displacement bar toward A). Target = A.
- Params: anchor [open@00:00]; d pts|%|sigma:k|datr:k [0] (38-80 pt; 0.25 sigma of daily changes); trigger {time,touch,bos,disp} [time]; t_in [09:30]; win [09:30, 11:30]; stop [level:extreme_since_anchor] (pts:25); tgt [level:A] (pts:38, R:2, pdh/pdl); flat [12:00].
- Res: 1m (5m). Data: price_bars.

### F13 PIVOT: Pivot-level rules (~14)
- Def: Ladder from the prior day's H, L, C: floor (P, R1-R3, S1-S3), Camarilla (H3, H4, L3, L4), CPR (P, BC, TC), Wilder (B1, S1, HBOP, LBOP), R-Breaker (6 levels). Mode: fade (first touch of R1 -> short, S1 -> long; stop R2/S2; target P), break (bar closes beyond R1/H4 -> with it; stop P/H3), reclaim (below S1, then a close back above), rbreaker (break of Bbreak/Sbreak when flat; reversal after Ssetup then below Senter), pullback (first retrace to a broken pivot).
- Params: set {floor,camarilla,cpr,wilder,rbreaker} [floor]; mode [fade]; sig_res [5m]; stop [level:next]; tgt [level:P] (none); prior_day {rth,globex} [rth]; win [09:30, 16:00].
- Res: 5m signals, 1m fills, daily levels. Data: price_bars.

### F14 GRID: Fixed price-grid levels (~8)
- Def: Ladder not taken from yesterday's bar: round-number endings (xx20/xx80, xx66), Gann square-of-9 steps from an anchor price, fixed-size grids (81/324/648 pt), or n x a reference range projected from its edges. Mode: fade (limit as price arrives: sell rising into it, buy falling into it), pierce (pierce, then a close back within m bars), break (stop-and-reverse through the nearest level).
- Params: grid {round:20/80,round:66,gann9,fixed:size,proj:n} [round:20/80]; mode [fade]; m [3]; win [09:30, 11:30]; stop [pts:10] (pts:25); tgt [pts:15] (pts:25); max_tr [3].
- Res: 1m. Data: price_bars.

### F15 NBAR_BREAK: Swing / N-bar / box breakout (~19)
- Def: Level = last confirmed fractal (k bars each side), n-bar high/low (Donchian), day high/low so far, an n-bar consolidation box, or a pivot zone with >= 2 touches. Entry: close beyond -> next open; resting stop at the level; or retest (first pullback that holds the level). Exit: stop at the opposite fractal/box side with an R target, or the opposite exit_n-bar extreme.
- Params: lvl {fractal:k,donchian:n,hod_lod,box:n,zone} [fractal:2]; n [20] (70; 16 = 4h of 15m); entry {close,stop,retest} [close]; res [15m]; stop [swing] (atr:1, pts:25-50); tgt [R:2] (pts, none); exit_n [none] (10); filt: adx(14)>25, ema trend, anchor side, window.
- Res: 15m (5m, 30m, 60m). Data: price_bars.

### F16 SWING_SWEEP: Swing stop-run reversal (~10)
- Def: Level = latest confirmed swing (k each side) or n-bar extreme. A bar trades beyond it by >= buf. Trigger: close_back (that bar or one of the next m closes back inside -> next open against the run), reclaim_bar (first close beyond the opposite end of the bar that made the extreme), gap_mid (limit at the midpoint of the first FVG of the reversal). Stop beyond the run extreme; target 2R.
- Params: k [5] (2); n [20]; buf pts [0.5]; m [1] (6); trigger [close_back]; res [5m] (1m, 15m, 60m, 1d); stop [bar] (atr:1.2); tgt [R:2] (R:2.5, range mid/opposite); trail [none] (bars:2); win [09:30, 16:00].
- Res: 5m (1m, 15m, 60m, 1d). Data: price_bars.

### F17 FVG_WINDOW: Fair-value-gap entry in a time window (~24)
- Def: Trade the first FVG (size >= gmin) that forms inside a window, in its direction. Optional preconditions: sweep (prior lookback extreme swept first; only FVGs against the sweep), disp (middle bar body >= k*atr and >= 70% of its range), trend (HTF EMA side), nest (inside an active HTF FVG). Entry: limit at the near edge on the first return (alt: midpoint, or market at the gap-completing close). Stop beyond the 3 FVG bars; target 2R; cancel at window end.
- Params: wins [[10:00,11:00]] (03:00-04:00, 14:00-15:00, 09:30-10:00, 07:00-10:00, all RTH); res {1m,5m,15m} [5m]; gmin [0.25]; entry {edge,mid,close} [edge]; pre [none]; sweep_lb min [120]; stop [bar] (far edge, sweep extreme, pts:12); tgt [R:2] (R:1, pts:20, liquidity level); flat [win end + 60m].
- Res: 5m (1m, 15m), 1m fills. Data: price_bars.

### F18 SWEEP_MSS_FVG: Sweep -> structure shift -> FVG/OB retrace (~21)
- Def: In a kill zone: (1) sweep of a level in lvls; (2) MSS within m bars (optionally body >= b*atr); (3) limit at the near edge (alt: midpoint) of the FVG left by the shift leg, or of the order block (last opposite-colour bar before the shift); alt: a close in the new direction after the zone is retested. Stop beyond the sweep extreme; target 2R or the opposite liquidity level.
- Params: lvls {pdh,pdl,asia,london,on,hour,htf_swing,eq_hl} [pdh,pdl,asia,london]; win [09:30, 11:00]; res [5m] (1m entry); k [3] (5, 8); m [40]; zone {fvg,ob,either} [fvg]; entry {edge,mid,retest_close} [edge]; stop [bar]; tgt [R:2] (level; 1.5R + 4R split); filt: HTF bias (daily EMA20, 4H EMA50).
- Res: 5m structure, 1m entry. Data: price_bars.

### F19 IFVG: Inversion-FVG entry after a sweep (~10)
- Def: After a sweep of a key level (as F18), an FVG formed in the sweep leg is inverted: a bar closes through its far edge -> enter at that close (alt: limit on the retest; or the retest of a balanced price range = overlapping opposite FVGs). Optional cisd: a close through the open of the run that made the extreme. Stop at the sweep extreme / last swing; target 2R.
- Params: lvls [pdh,pdl,asia,london] (range 08:00-09:30, 08:12-09:12, equal highs/lows); win [09:30, 11:00]; res [1m]; gmin [0.25]; entry {close,retest,bpr} [close]; cisd 0/1 [0]; stop [swing]; tgt [R:2] (R:1.5, opposite range edge).
- Res: 1m (5m). Data: price_bars.

### F20 ZONE_RETEST: Order-block / supply-demand zone retest (~9)
- Def: Zone = order block (last opposite-colour bar before an impulse >= k*atr), base (1-3 small bars between two impulse legs), confirmed pivot widened by an ATR fraction, or the wick tip closed through by an HTF displacement bar. Trade the first return in the impulse direction: limit at the proximal edge, or touch + confirmation bar. Stop beyond the distal edge; target 2R.
- Params: zone {ob,base,pivot,poi} [ob]; k [1.5]; zone_res [15m] (1m, 5m, 1h); entry {limit,confirm} [limit]; stop [level:distal] (pts:20, atr:1.5); tgt [R:2] (R:1, atr ladder); win [09:30, 15:55]; filt: ema(200) side, rsi, after an overnight-range sweep.
- Res: 15m zones (1m, 5m, 1h), 1m/5m entry. Data: price_bars.

### F21 FIB_RETRACE: Fibonacci / OTE retracement limit (~8)
- Def: Leg = latest impulse (ZigZag leg >= z*atr, MSS leg, first-hour range, two-bar impulse, hourly dealing range). Limit at retracement f in the leg's direction; cancel if a bar closes beyond f first. Stop at retracement fs; target = leg extreme.
- Params: leg {zigzag:z,mss,first_hour,two_bar,h1_range} [zigzag:3]; f [0.618] (0.5, 0.705, 0.62-0.79); fs [0.786] (1.0); tgt [level:leg_extreme] (R:k, extension); res [5m]; filt: trend, twap side, window.
- Res: 5m (1m, 15m, 60m). Data: price_bars.

### F22 IMPULSE: Displacement / impulse-bar continuation (~12)
- Def: Impulse = displacement bar (body > previous body and close beyond the previous wick, body >= x), wide-range bar (>= k x average range), close-to-close jump >= x, or a run of n same-direction bars covering >= y% of the average daily range; optionally only in the first m minutes after a session open. Enter with it at its close, or on the first pullback. Stop at the impulse bar's far extreme or fixed points.
- Params: sig {disp,wide:k,jump:x,run:n,y} [disp]; opens [09:30, 14:00, 20:00]; m [10] (none); x pts [18] (30); entry {close,pullback} [close]; res [1m] (5m); stop [pts:25] (bar); tgt [pts:38] (R:1, R:2); max_tr [1 per session].
- Res: 1m (5m). Data: price_bars.

### F23 LATE_DIR: Day-so-far return -> afternoon trade (~21)
- Def: At t_in >= 12:00, direction = sign of the return from ref to t_sig, traded with it (follow) or against it (fade) until t_out; skip if |return| < thr. Optional conditions: a second window with the same sign, gap size/sign, prior-day return sign, close location in the day's range, day range >= x, weekday, daily SMA regime.
- Params: ref {prev_close,open,open@18:00,price@T,day_mid} [prev_close]; t_sig [10:00] (15:30, 14:45, 15:00); t_in [15:30]; t_out [16:00]; mode {follow,fade} [follow]; thr %|pts [0] (1.25%, 2%, 3 pt); cond [none]; stop [none] (datr:0.5); tgt [none].
- Res: 1m/5m at fixed times. Data: price_bars.

### F24 NOISE_AREA: Noise-area band breakout (~16)
- Def: sigma(t) = mean over lb sessions of |price(t)/RTH open - 1| at the same minute. Upper = max(open, prior close) x (1 + vm*sigma), lower = min(open, prior close) x (1 - vm*sigma). At each chk-minute mark 10:00-15:30: long above upper, short below lower. Exit at a check when price is back through max(upper, P) for longs (mirror for shorts); flat 16:00.
- Params: lb [14] (90); vm [1]; chk {1,5,15,30} [30]; exit {band_or_P,band,P,opp} [band_or_P]; stop [none] (datr:0.2); filt: gap up, long only, ema(100) on 1m.
- Res: 1m, checks every 30 min. Data: price_bars.

### F25 GAP: Opening-gap fade or continuation (~23)
- Def: Gap = 09:30 open - prior 16:00 close (alt: open beyond the prior day's high/low). If gmin <= |gap| <= gmax: fade (against the gap at the open, target the prior close) or follow (with the gap at the open, or by a stop beyond the first 5m bar when it closes in the gap direction). Stop = one gap-size beyond entry; exit at t_out.
- Params: unit {%,pts,datr,z60} [%]; gmin [0.10]; gmax [none] (0.75%, 0.4 datr); mode {fade,follow} [fade]; entry {open,confirm5m,t} [open]; tgt [level:prev_close] (half gap, pct:0.5, R:2, none); stop [gap x 1] (pct, datr, bar); t_out [16:00] (10:00, +60m); filt: gap dir, open inside prior range, prev_day, dow, opex, sma_d.
- Res: 1m/5m, daily references. Data: price_bars.

### F26 TOD_WINDOW: Fixed time-of-day window (~15)
- Def: Enter at a fixed clock time in a direction fixed in advance, exit at a fixed clock time; several legs allowed. Optional condition known before entry: weekday, prior-day bar shape or EMA side, yesterday's return in the same slot, prior-day sell-off. No same-day price signal.
- Params: legs (t_in,t_out,dir) [(09:30,15:59,long)] (23:30->03:30 L; 02:00->03:00 L; 09:00->10:00 S; 11:00->12:00 S + 12:00->14:00 L; 14:00->15:45 L); cond {none,dow,prev_day,same_slot} [none]; stop [none] (pts:30); tgt [none] (pts:90).
- Res: 1m at fixed times. Data: price_bars.

### F27 CALENDAR_DAY: Calendar-day holds (~12)
- Def: Hold over whole sessions picked by the calendar: turn of month (last trading day -> 3rd), pre-holiday day, 3rd-Friday expiry (Thu close -> Fri open long; Fri open -> close short; expiry week long), T-8..T-4 before month end (short), the 16th, even FOMC-cycle weeks, Monday in Friday's direction, weekday holds. Entry/exit at the 16:00 close, 18:00 open or 09:30 open. Needs a built-in holiday/expiry/FOMC date table.
- Params: anchor {tom,pre_holiday,opex_fri,opex_week,month_end,day16,fomc_week,mon_fri,dow_hold} [tom]; a,b trading-day offsets [-1,+3]; t_in,t_out {close,18:00,09:30} [close]; dir {long,short,sign_prev} [long]; filt: sma_d(200), sma_d(50).
- Res: session boundaries from 1m bars; daily closes. Data: price_bars.

### F28 MACRO_EVENT: Scheduled-release windows (~11)
- Def: Only on release days, timed from release time T (CPI/NFP 08:30, FOMC 14:00, press conference 14:30): pre (long from t0 to T-5m or T+15m, % stop), day (long the announcement session), range_break (range of T..T+15/30m; first close beyond -> with it), range_fade (fade that first break), straddle (stops +/- x pt around price before T), post_day (short the session after the FOMC day), stmt_pc (sign of the T-10..T+20m return, traded from 14:30). Needs a built-in release-date table.
- Params: events {fomc,cpi,nfp,gdp,ism,ppi} [fomc,cpi,nfp]; mode [pre]; t0 [T-5m] (prior close, 18:00); t_out [T+15m]; rng_min [15]; x pts [10]; stop [pct:0.10] (pct:0.20, rng:1, none); tgt [none] (R:k).
- Res: 1m/5m around release times. Data: price_bars.

### F29 MA_CROSS: Moving-average state flip (~27)
- Def: State from MAs: price vs MA, fast vs slow MA, three MAs in order (5/8/13, 4/9/18, 13/8/5 smoothed), or MA slope sign (Hull turn, regression slope beyond a threshold). On a state change enter at the next open: always-in reversal, or flat until the next new alignment. Exit on the opposite state or at flat.
- Params: form {price_ma,fast_slow,stack3,slope} [fast_slow]; type {sma,ema,kama,hma,smma,lsma} [ema]; lens [9,20] (5/30, 20/50, 12/26, 50, 120/600); res [15m] (1m, 5m, 10m); always_in [1]; delay min [0]; hold [none] (10 bars); stop [none] (atr:1, beyond slow MA); tgt [none] (atr:2); win [09:30, 15:45]; filt: macd sign, ema(200), twap side.
- Res: 15m (1m, 5m, 10m). Data: price_bars.

### F30 TREND_FLIP: Trend-indicator flip (~18)
- Def: State from one indicator: Supertrend(10,3), Parabolic SAR(0.02,0.2), Chandelier Exit(22,3), ATR trailing stop 'UT Bot'(1,10), percent trailing reverse, Heikin-Ashi colour, Ichimoku Tenkan/Kijun(9,26) cross (optional cloud filter), Aroon(25), Vortex(14), +DI/-DI(14) cross with ADX>25, SSL channel above a baseline. Enter at the next open after a flip; exit or reverse on the opposite flip.
- Params: ind {supertrend,psar,chandelier,utbot,nrtr,heikin,ichimoku,aroon,vortex,dmi,ssl} [supertrend]; p [textbook]; res [15m] (1m, 5m, 60m); always_in [1]; stop [none] (atr:2); tgt [none] (R:2); filt: adx>25, cloud side, zlsma side, ema(200).
- Res: 15m (1m, 5m, 60m). Data: price_bars.

### F31 OSC_MOM: Momentum-oscillator signal (~23)
- Def: Trade with an oscillator signal: MACD(12,26,9) signal or zero cross, ROC(12) zero, Awesome Oscillator zero, TRIX(15,9), Fisher(9), Coppock(14,11,10) turn, 3/10 oscillator, CCI(14) zero-line patterns, RSI(14) crossing above 70 (long) / below 30 (short) with exit at 50, stochastic thrust above 75 / below 25, smoothed stochastic vs its signal, phase oscillator +/-100, momentum(28) vs its MA. Exit on the opposite signal or the stated level.
- Params: osc {macd_sig,macd_zero,roc,ao,trix,fisher,coppock,o310,cci,rsi_break,stoch_thrust,stoch_sig,phase,mom_ma} [macd_sig]; p [textbook]; res [15m] (5m, 10m, 45m, 60m); exit {opp,level,opp_extreme} [opp]; stop [none] (atr:2); tgt [none]; win [09:30, 15:45]; filt: ema(200) side, histogram threshold.
- Res: 15m (5m, 10m, 45m, 60m). Data: price_bars.

### F32 MA_PULLBACK: Pullback to a moving average in a trend (~28)
- Def: Trend by MA side/slope, fast>slow MAs, an HTF EMA, or ADX>x rising. A bar touches the pullback MA after >= away bars off it. Trigger: close_back (closes back on the trend side -> next open), stop_bar (stop 1 tick beyond the touch bar, valid v bars), limit (at the MA), nth (only the n-th pullback), wick (rejection wick >= w x body). Stop at the touch bar's far extreme; target in R or the prior swing.
- Params: pb_ma [ema,20] (8, 9, 21, 50, 200, kalman); trend {side_slope,fast_slow,htf_ema,adx:30} [side_slope]; trigger [close_back]; away [3]; v [1]; res [5m] (1m, 15m, 60m, 1d); stop [bar] (atr:1.5, pts, beyond slow MA or P); tgt [R:2] (R:0.75, R:1, swing, none = exit on a close beyond the MA); max_tr [2]; win [09:30, 15:30]; filt: twap side, skip first hour.
- Res: 5m (1m, 15m, 60m, 1d). Data: price_bars.

### F33 CONFLUENCE: Multi-indicator gate with bracket (~15)
- Def: Enter at the next open when every condition in conds is true (one just turned true); short = mirror. Vocabulary: ema(a)>ema(b); close>ma(n); ma slope; rsi(n) vs x; adx(n)>x; macd>signal or hist>x; close>highest(n); close>close[n]; atr rising; close vs P; HTF candle colour; supertrend/alligator/%R state. Exit by bracket, by a named condition turning false, or by time.
- Params: conds [ema9>ema21, close>ema9, rsi14>50]; res [5m] (1m, 15m); stop [atr:1.5] (pts:10-15, pct:0.05); tgt [R:2] (pts:20, pct:0.1); exit_cond [none]; win [09:30, 11:30]; max_tr [3].
- Res: 5m (1m, 15m). Data: price_bars.

### F34 OSC_MR: Intraday oscillator mean reversion (~10)
- Def: Fade an oscillator extreme: RSI(n) crossing back above lo -> long / below hi -> short, stochastic cross inside the zone, CCI turning back through -/+100, Williams %R, WaveTrend zone cross, cumulative RSI(2), a close at an n-bar low with the 200-SMA trend, or regular divergence (price lower low, oscillator higher low between pivots 5-60 bars apart). Exit at neutral, the opposite extreme, a short-MA cross, or bracket/time.
- Params: osc {rsi,stoch,cci,wr,wavetrend,cumrsi,nbar_low,divergence} [rsi]; n [14] (2, 5, 6); lo,hi [30,70]; entry {cross_back,in_zone} [cross_back]; exit {neutral,opp,ma:5,bars:n,bracket} [neutral]; trend {none,sma200,daily_sma200} [none]; res [15m] (1m, 5m, 30m, 60m); stop [none] (atr:1); tgt [none] (R:2).
- Res: 15m (1m, 5m, 30m, 60m). Data: price_bars.

### F35 BAND_MR: Band / envelope mean reversion (~13)
- Def: Fade an excursion beyond an envelope: Bollinger(20,2), Keltner(EMA20, 2*ATR), previous close -/+ k*ATR (resting limit), MA +/- fixed points, SMA-of-highs/lows channel, kernel envelope, z-score over n bars beyond +/-z, or MA-stretch (|SMA50 - SMA200| >= s and a close back across SMA50 toward SMA200). Entry: close beyond -> next open, limit at the band, or the close back inside. Exit at the centre line.
- Params: env {boll,keltner,atrband:k,ma_pts,hl_sma:n,nw,zscore:n,z,stretch:s} [boll]; n,k [20,2]; entry {close_out,limit,close_in} [close_out]; confirm {none,rsi} [none]; exit {mid,opp,slow_ma,bars:1} [mid]; stop [none] (atr:1.5, pts); tgt [none] (atr:2); res [5m] (1m, 15m, 30m).
- Res: 5m (1m, 15m, 30m). Data: price_bars.

### F36 BAND_BREAK: Volatility-band breakout (~11)
- Def: Trend entry on a close beyond a band: Bollinger(20,2), Keltner(EMA20, 2*ATR), MA channel of highs/lows (SMA10 highs / SMA8 lows, EMA34; n bars fully outside), >= 2 of 3 HTF Bollinger bands (5m, 15m, 1h), squeeze release (Bollinger inside Keltner(20,1.5), then out; direction = momentum sign), or a stop at rolling midpoint +/- k*ATR. Exit on a close back through the middle line.
- Params: band {boll,keltner,ma_chan,mtf_boll,squeeze,mid_atr} [boll]; n,k [20,2]; res [15m] (1m, 5m, 10m, 30m); entry {close,stop} [close]; exit {mid,opp,bracket} [mid]; stop [none] (atr); tgt [none]; filt: adx, HTF sma, window.
- Res: 15m (1m, 5m, 10m, 30m). Data: price_bars.

### F37 VOL_BREAK: Open-anchored volatility breakout (~33)
- Def: Levels = anchor + ku*V and anchor - kd*V, set at the session open; resting stops, the first one touched sets the direction. V = prior-day range, n-day average range, daily ATR, Crabel stretch (10-day mean of min(H-O, O-L)), Dual-Thrust range max(HH-LC, HC-LL), greatest-swing value, noise-ratio K x prior range, % of the open, the prior day's larger close-to-extreme offset, or the average range of the first 6 5m bars. Exit at the close; the opposite level is the stop (or reverses).
- Params: anchor {open,prev_close,open@00:00} [open]; entry {stop,close} [stop]; V [prev_range]; ku,kd [0.5,0.5] (stretch 1; dual 0.5-0.7; gsv 1.8; datr 0.236-1; pct 0.5-2); reverse 0/1 [0]; stop [level:opp] (none, pts, level:open); tgt [none] (pts, datr:0.618, next open, first profitable open); setup {none,NR7,NR4,ID_NR4,range<avg,cmi} [none]; win [09:30, 15:30].
- Res: 1m fills, daily volatility inputs (5m/15m/30m bars in some). Data: price_bars.

### F38 TWAP_TREND: TW-VWAP-proxy trend (~10)
- Def: P replaces VWAP (label results 'TW proxy'). cross: long when a bar closes above P, short below, flip on each close across; ema_cross: EMA(n) crosses P and a bar closes beyond both, exit on the cross back; side_at: at a fixed check time take the side of P and hold to the close; flip_bar: a strong bar closes across P, 1R.
- Params: anchor [09:30] (00:00, 18:00); mode {cross,ema_cross,side_at,flip_bar} [cross]; res [1m] (3m, 5m, 15m); n [9] (11); t_chk [10:15] (10:45, 11:45); stop [none] (atr:1 beyond P, swing); tgt [none] (R:1); t_out [16:00].
- Res: 1m (3m, 5m, 15m). Data: price_bars.

### F39 TWAP_MR: TW-VWAP-proxy deviation fade (~14)
- Def: sigma = running SD of typical price around P. Fade a stretch from P: band (touch/close beyond P +/- k*sigma), pts (>= x points from P), ouz (|z| > 2 of an OU fit of close - P with Hurst < 0.45), cross (fade every cross of P). Optional confirmation: RSI(14) < 30 / > 70, reversal bar, two closes back through MA(9), FVG close-back, n-th event only. Target = P; timeout.
- Params: dev {band:k,pts:x,ouz,cross} [band:2] (1, 1.5, 2.5, 3; 6 pt); entry {touch,close} [touch]; confirm [none]; tgt [level:P] (half-way, atr:1.1); stop [0.75 band-width beyond entry] ((k+1) sigma, atr:1); hold [60 bars] (20); res [1m] (5m); win [10:00, 15:00]; anchor [09:30] (00:00, 18:00).
- Res: 1m (5m). Data: price_bars.

### F40 TWAP_PULLBACK: TW-VWAP-proxy pullback in a trend (~13)
- Def: Regime vs P: drift (close above P, P rising, +0.1% over the past hour on 15m bars), side_slope (above P with a rising EMA), or_break (after a close above the opening-range high). Entry with the regime: counter_bar (first bar closing against it -> next open), touch (a bar touches P or its 0.25-sigma zone and closes back), limit (at P on the first touch after a pull-away), break (close above the prior n-bar high with a wick near P).
- Params: regime [drift]; trigger {counter_bar,touch,limit,break:n} [counter_bar]; res [5m] (1m; regime on 15m); stop [pts:80] (10 ticks, beyond P, swing); tgt [pts:40] (R:2, 10-15 ticks, none); win [10:30, 15:30]; flat [15:55]; max_tr [5]; filt: adx>20 and not rising, rsi reset.
- Res: 5m entry, 15m regime (1m). Data: price_bars.

### F41 CANDLE: Candle / signal-bar pattern (~16)
- Def: A bar pattern completes; trade its textbook direction: hammer / shooting star (wick >= 2x body), engulfing, morning/evening star, inside bar (break of the mother bar), ii/iii, hikkake, two-bar reversal, 3-bar fractal turn, wick/extreme reversal (wick >= 3.25x body, range >= 1.1x average), failure-to-go-high/low, wickless bar, tail bar at an EMA. Entry: next open, stop beyond the signal bar, or limit at a signal-bar price. Stop beyond the pattern; target 2R or exit after n bars.
- Params: pat [inside]; entry {next_open,stop,limit} [next_open]; res [15m] (5m, 13m, 60m); stop [bar] (none); tgt [R:2] (pts, bars:1, bars:3); filt: ema side, stochastic, level proximity.
- Res: 15m (5m, 13m, 60m). Data: price_bars.

### F42 RUN_COUNT: Consecutive-bar run rules (~11)
- Def: n closes in a row in one direction. follow: enter with the run at the next open, stop beyond the run's extreme, 2R; fade: enter against it, exit at the first close in favour; td9: 9 closes each beyond the close 4 bars earlier (optional countdown 13), fade; majority: more up than down bars in the last b bars and close < close[p] -> long; two_tf: m same-direction 5m bars, then k counter 1m bars -> with the 5m run.
- Params: n [3]; mode {follow,fade,td9,majority,two_tf} [follow]; res [15m] (5m, 60m, 1d); stop [bar] (none); tgt [R:2] (none); filt: momentum, HTF ma.
- Res: 15m (5m, 60m, 1d). Data: price_bars.

### F43 ZIGZAG_FORM: Swing-structure formations (~12)
- Def: Swings from a ZigZag (turn >= z*atr) or k-bar pivots, used only once confirmed. When a formation completes and a bar closes beyond its trigger line within 20 bars -> next open. Formations: head-and-shoulders, double top/bottom, flag (pole >= 5.5 ATR in <= 23 bars, flag <= 15 bars), triangle, three-push wedge, AB=CD, harmonic XABCD (entry at D), Quasimodo, 1-2-3 / Ross hook / two-leg pullback, Wolfe wave, trendline through the last two swings. Stop beyond the last swing; target 2R or the measured move.
- Params: form [double]; z [2] (1, 3, 4); k [5]; res [5m] (15m, 60m, 1d); stop [swing]; tgt [R:2] (R:1, R:4, measured).
- Res: 5m (15m, 60m, 1d). Data: price_bars.

### F44 TPO_VALUE: Value-area rules from bars (TPO proxy) (~14)
- Def: Prior RTH profile without volume: each 30-min period marks each price bucket it traded; POC = bucket with most marks; value area = 70% of marks grown from the POC (VAH, VAL). rule80: open outside the prior VA, two consecutive 30-min closes inside -> toward the opposite edge; edge_fade: a probe beyond VAH/VAL closes back inside -> fade to the POC (or hold 60/120 min); poc: untouched prior POC as target or first-touch fade; close_loc: prior close above/below its own VA -> next-day long/short; inventory: overnight mostly beyond the prior VA -> fade at the open; poc_shift: buy pullbacks to a rising developing POC.
- Params: bucket pts [1]; va [0.70]; mode {rule80,edge_fade,poc,close_loc,inventory,poc_shift} [rule80]; accept [2 periods] (60 min); stop [re-entry edge + atr:0.5] (session or probe extreme); tgt [level:opp_edge] (level:poc, pts).
- Res: 30m periods built from 1m; 1m/5m entry. Data: price_bars.

### F45 DAILY_DIP: Daily pullback / dip-buy (~15)
- Def: Daily RTH bars. Long at the close when a pullback signal holds, by default only above the 200-day SMA: RSI(2) < 10, cumulative RSI(2) < 35, lowest close of 7 days, %R(10) < -90, close < fast SMA and in the bottom 20% of the bar, 3 lower closes, negative weighted sum of the last 4 returns, 2-day force index < 0 in a rising weekly MACD histogram, a down day on high daily volume, limit 1% under Monday's open. Exit on the stated recovery rule. Session variants enter at 18:00 and exit after h hours.
- Params: sig {rsi:n,lo,cumrsi,low_close:n,wr,ibs,closes_down:n,wret,force,vol_down,wk_limit} [rsi:2,10]; trend {sma200,none} [sma200]; exit {rsi>70,close>sma5,high_close:7,wr>-20,close>prev_high,bars:n} [rsi>70]; entry {close,next_open,18:00} [close]; stop [none] (datr:2, pct:5); h [none] (8); filt: dow, week of month.
- Res: 1d (18:00 session variants on 60m). Data: daily_bars.

### F46 DAILY_BAR: Daily bar pattern, close entry (~6)
- Def: A daily bar pattern completes at the close; enter at that close or the next open; exit at the next close, the first profitable close, or after n days. Patterns: gap-down reversal (open < prior low, close > open and in the top half), outside day with a lower close (short when R-squared of 80 closes > 0.5; or long at the next open when it closes below the prior low), weak prior bar then a new 5-day high. Next-day stop entries beyond the setup bar belong to F09.
- Params: pat {whiplash,outside_down,outside_trend_short,ibs_newhigh} [whiplash]; entry {close,next_open} [close]; exit {next_close,first_profit_close,days:n,close>prev_high} [next_close]; stop [none] (pts:50).
- Res: 1d. Data: daily_bars.

### F47 DAILY_TREND: Daily trend / breakout swing (~4)
- Def: Multi-day systems on daily bars: n-day breakout with m-day opposite exit and 2*ATR(20) stop (20/10, 55/20), 40-day typical-price Keltner stop entry exited at the average, n-day momentum zero cross, 2-period ROC pivot flip, daily MA trend. Positions carry overnight (the harness chooses the published hold or a session-by-session version).
- Params: sys {donchian:n,m,keltner:40,mom:n,roc2,ma:n} [donchian:20,10]; stop [atr20:2] (none); filt: rsi(2)<90, skip after a winner.
- Res: 1d. Data: daily_bars.

### F48 XSERIES: Rules gated by another daily series (~11)
- Def: Signal or gate needs another DAILY series that must be downloaded (VIX, VXN, VIX9D, 10-year yield or T-bond, ES daily). vix_rev: VIX n-day high closing below its open -> buy the close, hold 1-3 days; vix_stretch: VIX >= 5% above its 10-day MA for 3 days, price above SMA200 -> buy, exit RSI(2) > 65; vix_jump: VIX minus its EWMA > 3 -> long the next session; vix_gate: a base family's rule only when VIX is above/below x; implied_band: fade or bracket at prior close/open +/- the one-day move implied by VIX/sqrt(252) or VXN/16; bond: 60/40 drift-weight signal, bond-index correlation gate, index/bond ratio EMA cross. If the other series is needed intraday -> X_DATA.
- Params: series {vix,vxn,vix9d,tnx,bond,es} [vix]; mode {vix_rev,vix_stretch,vix_jump,vix_gate,implied_band,bond} [vix_gate]; base family key [none]; n [15]; x [20]; band_k [1].
- Res: 1d (some with 1m/5m execution). Data: needs_other_daily_series.

## X keys (not testable as a family)
- **X_TICK** (~44): Needs tick, order-book, footprint, delta/CVD, DOM or tape data; or bars finer than 1 minute or built from ticks (30-second, tick, range, Renko); or brackets of a few ticks that 1-minute OHLC cannot resolve.
- **X_VOLUME** (~26): Intraday volume is the core signal (volume spike or relative volume, OBV, CMF, MFI, VWMA, VSA, VPIN, volume profile or volume POC with no TPO stand-in). The 16-year bars have no volume, so this is testable only on the 49-session MNQ 5-minute file (Aug-Oct 2026), too short for a verdict. Record x_sub (vol_spike_bar, vol_profile, obv ...). Not for volume as a side filter (drop it, vol_dropped=1) or for VWAP (use the P proxy, F38-F40).
- **X_DATA** (~34): Needs other data that is not available: options flow, dealer gamma or strikes; news or sentiment feeds; market internals ($TICK, ADD, VOLD, breadth); closing-auction imbalance; ETF/ETP assets, dividends, earnings counts, forecasts; crypto or fed-funds futures; another market's intraday bars (ES, YM, NDX cash, intraday VIX: SMT divergence, pairs, relative strength).
- **X_DISCRETION** (~29): No mechanical rule and no standard coded form: hand-drawn levels or trendlines, discretionary bias, 'context' or day-type reads, playbooks, setups whose trigger is not defined.
- **X_ML** (~18): A trained or fitted model without a full fixed specification: GMM/HMM regimes, LSTM, gradient boosting, kNN, reinforcement learning, fitted regressions, Kalman or velocity filters with unpublished settings, parameters re-optimised walk-forward.
- **X_NOT_A_STRATEGY** (~51): No testable entry rule: a risk or position-sizing overlay, a statistic or study with no trade, a survey of a whole rule universe, a track record, CTA program, black box, paid signal service or paywalled rule; a wrapper whose components are separate records; a null benchmark (coin toss).

## Data notes for the test modules
- F27 and F28 need date tables (holidays, 3rd Fridays, FOMC, CPI, NFP) compiled into the module; no price data beyond the bars.
- F48 needs daily VIX / VXN / VIX9D / bond series that are not in the data folder.
- F45-F47 can use `research2/data/NQ_F_1d.csv` (daily since 2000, with volume), so daily rules that use daily volume are computable.
- F38-F40, F24's exit and every `twap` filter use P, a time-weighted proxy. F44 uses TPO counts where sources used volume. Report both as proxies.
- X_VOLUME: the only repeated precise sub-shape is the volume-spike bar (bar volume >= 2x its 20-bar average -> trade the bar's direction, stop beyond the bar, 2R), about 6 records; it could be spot-checked on the 49-session MNQ file.
