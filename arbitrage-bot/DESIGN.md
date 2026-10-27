# arbbot design and module contracts

This file is the spec each module is built against. The foundation modules
(`models.py`, `config.py`, `portfolio.py`, `clock.py`, `mathutil.py`,
`journal.py`, `feeds/base.py`, `execution/base.py`) define the shared types;
read them first. Units are fixed: price = quote per base, size = base units,
money = quote currency, time = float epoch seconds from the injected `Clock`.

## Data flow

```
venue websockets ──► Feed.stream() ──► Bot.handle_event(ev)
                                         │ QuoteBook.update / invalidate_venue
                                         │ RiskManager.on_quote / on_feed_status   (liquidity gate)
                                         │ PositionMonitor.on_quote                 (stops/targets/time exits)
                                         │ CrossVenueScanner / ReferenceLagScanner.on_quote ─► Signal
                                         │ Journal.record("signal")
                                         │ RiskManager.check(signal) ─► RiskDecision (approve + size, or reason)
                                         │ ExecutionEngine.execute / enter ─► ExecutionReport
                                         │ RiskManager.on_execution(report)          (PnL, kill switch)
                                         ▼ Journal.record("execution")
```

Backtests drive the exact same objects from a recorded quote file with a
`SimClock` and `PaperExchange` fills taken from the book *as of order
arrival time* (signal time + venue latency), never the signal-time book.

Money is in each symbol's quote currency and summed across symbols at par, so
every configured symbol must be quoted in USD or a USD stablecoin
(`config.USD_LIKE_QUOTES`); `validate` refuses anything else (a BTC-quoted
symbol would make `max_order_notional = 500` mean 500 BTC).

## Non-negotiable invariants

1. Never compare different canonical symbols (BTC-USD vs BTC-USDT carry a
   floating basis; that is not an arb). Cross-venue pairs share a symbol.
2. No trading on stale data: a quote older than `risk.max_quote_age_ms`, or
   from a venue whose feed reported disconnect, is unusable.
3. An emitted signal's net edge is after taker fees on every leg, expected
   slippage on every leg, and `signal.min_net_edge_bps` buffer.
4. Every trade has a bounded worst case: entry limits cap slippage at
   `execution.max_slippage_bps`; any unhedged residual is hedged or unwound
   with limits capped at `execution.unwind_slippage_bps`; directional
   positions have a hard stop and a time stop.
5. Never leave a half-open arb silently. Unequal fills are hedged/unwound
   immediately; anything still unhedged (RESIDUAL) or unknown (UNKNOWN) trips
   the kill switch. The one exception is *dust*: a remainder no order on any
   involved venue can trade (below its lot, or below its `min_notional` at the
   limit the order would carry). It is reported (FLATTENED / CLOSED with a
   dust note and `residual_qty`), stays in the exposure figures, and does not
   trip the kill switch. Orders a venue is certain to refuse are never sent.
6. Risk limits are code, checked on every signal, and only the operator can
   reset a tripped kill switch. Exits are never blocked by risk.
7. Deterministic: no wall-clock reads or unseeded randomness outside
   `WallClock` / explicit seeds, so a backtest replays identically. Ids come
   from a per-`Bot` `IdFactory` (`sig-1`, `pos-2`, ...), so two identical
   runs in one process write identical journals; ids are unique within a run.
8. The engine is the only writer of `Portfolio` (it applies every fill).
   Inventory an open directional position needs for its exit is reserved
   (`Portfolio.set_reservations`): `sellable` / `buying_power` exclude it.
9. Journaling never strands a trade: a failed journal write is logged,
   alerted and trips the kill switch (`journal_error`); alerts are sent before
   the matching journal write.

## feeds — `feeds/venues.py`, `feeds/ws.py`, `feeds/recorder.py`, `feeds/replay.py`

`venues.py`
- `VenueAdapter` (dataclass or class) with:
  - `name: str`
  - `url(instruments: Sequence[InstrumentConfig]) -> str`
  - `subscribe_messages(instruments) -> list[str]` (JSON text frames; may be empty when the URL subscribes)
  - `heartbeat() -> tuple[float, str] | None` (interval seconds, app-level ping text) for venues that require one
  - `parse(raw: str | bytes, now: float, symbols: Mapping[str, str]) -> list[Quote]`
    where `symbols` maps venue_symbol -> canonical symbol. Non-quote frames
    (acks, pongs, status) return `[]`. Malformed frames raise `ValueError`.
- `ADAPTERS: dict[str, VenueAdapter]` with keys `binance`, `bybit`, `kraken`, `coinbase`, `okx`.
- Binance: market-data host `wss://data-stream.binance.vision` (combined
  streams `/stream?streams=btcusdt@bookTicker/...`), `seq = u`. Formats must be
  verified against each venue's official docs; record a real frame as a test fixture.

`ws.py`
- `WebSocketFeed(adapter, venue: VenueConfig, clock: Clock, *, connect=websockets.connect,
  stall_timeout_s=10.0, max_backoff_s=30.0, seed=0)` implementing `Feed`.
  `stream()` yields `FeedStatus(connected=True)` after subscribing, then
  `Quote`s; on any drop/stall/error yields `FeedStatus(connected=False, reason)`
  and reconnects with exponential backoff + seeded jitter (reset after a
  stable connection). Parse errors are logged and counted, never fatal.
  `stop()` ends the stream cleanly.
- `merge_feeds(feeds) -> AsyncIterator[FeedEvent]` fan-in through a bounded queue.

`base.py` — `QuoteBook` drops a quote whose `seq` is lower than the stored
one, or equal with different prices/sizes. The same `seq` with the same book
(Bybit re-sends an unchanged level-1 snapshot every 3 s with the same `u`) is
a re-confirmation: it is stored, refreshing `ts_local`. `BookView` is the
read-only `get(venue, symbol)` protocol the execution engine prices from.

`recorder.py` — `QuoteRecorder(path)` with `write(quote)` (JSONL, one Quote per
line, all fields) and `close()`; `async record(feeds, path, duration_s, clock)`.

`replay.py`
- `load_quotes(path) -> list[Quote]`: JSONL (recorder format) or CSV with
  header `venue,symbol,bid,bid_size,ask,ask_size,ts_local[,ts_exchange,seq]`,
  stably sorted by `ts_local`.
- `QuoteHistory(quotes)`: `as_of(venue, symbol, t) -> Quote | None` (latest
  quote with `ts_local <= t`, bisect per key), `events()` time-ordered, `start`, `end`.
- `generate_synthetic(venues, symbol, *, start_ts, duration_s, hz, base_price,
  vol_bps, spread_bps, depth, dislocation_rate, dislocation_bps, seed) -> list[Quote]`:
  deterministic random walk shared by all venues + per-venue noise + occasional
  short-lived dislocations on one venue. For demos and tests only.

## signal — `signal.py`

`CrossVenueScanner(cfg: BotConfig, clock: Clock)`
- `on_quote(quote, book, portfolio) -> list[Signal]`: evaluates only pairs
  involving `quote.venue` for `quote.symbol` (both directions), O(venues) per
  update. Returns at most one signal (the best net edge) per call.
- `evaluate_pair(buy_q, sell_q, portfolio) -> Signal | None` (pure math, no timers):
  - both quotes fresh (`age <= risk.max_quote_age_ms`), same symbol, different venues
  - `gross = edge_bps(buy_q.ask, sell_q.bid)`
  - `cost = fee_b + fee_s + slip_b + slip_s` (taker fee and slippage bps of each venue)
  - `net = gross - cost`; candidate iff `net >= signal.min_net_edge_bps` and `net > 0`
  - `size = participation * min(buy_q.ask_size, sell_q.bid_size)`, capped by
    `risk.max_order_notional / buy_q.ask`, by `portfolio.buying_power(buy venue,
    symbol, ask * (1 + max_slippage_bps/1e4), fee_b)` and `portfolio.sellable(sell venue, symbol)`,
    floored to both venues' lot sizes; None if notional < either venue's min_notional
  - `expected_pnl = size * (bid * (1 - (fee_s+slip_s)/1e4) - ask * (1 + (fee_b+slip_b)/1e4))`
  - `entry = ask`, `target = bid`, `stop = ask * (1 - unwind_slippage_bps/1e4)`
  - `market = f"{symbol} buy@{buy_venue} sell@{sell_venue}"`, legs = (BUY leg, SELL leg)
- Persistence: a pair must qualify continuously for `persistence_ms` before firing.
- Cooldown: emitting a signal for a pair suppresses that pair for `cooldown_ms`.
- `stats` exposes counts (evaluations, candidates, emitted) and fixed-bin
  histograms of the best gross and net edge per evaluation (for tuning X);
  `stats.summary() -> dict`.

`ReferenceLagScanner(cfg: BotConfig, clock: Clock)` (only when `reference_lag.enabled`)
- Tracks `premium_bps = (mid_target - mid_ref) / mid_ref * 1e4` with a
  time-decayed EMA (`alpha = 1 - exp(-ln2 * dt / basis_halflife_s)`, first sample initializes).
- On each target quote with a fresh reference quote: FIRST evaluate against the
  current basis, THEN fold the observation into the EMA. An observation stamped
  at the same time as the previous fold has zero weight and is not counted. No
  signals until `min_basis_samples` observations; at that point the basis is
  re-seeded with the MEDIAN of the warm-up premiums (`warm` becomes true), so
  no single early (possibly transient) observation dominates the slow EMA.
- `fair = mid_ref * (1 + basis/1e4)`; round-trip cost `= 2 * (fee_t + slip_t)`.
- BUY if `ask < fair`: `gap = (fair-ask)/ask*1e4`; the trade aims for
  `target = ask + take_profit_fraction*(fair-ask)`, so its edge is
  `gross = take_profit_fraction * gap` (entry to target, bps of entry);
  fire iff `net = gross - cost >= entry_threshold_bps` (and `> 0`).
  `gross_edge_bps = gross`, `net_edge_bps = net`; `entry=ask`,
  `stop = ask*(1-stop_bps/1e4)`. SELL mirrored (`bid > fair`; needs sellable
  base on the target venue).
- Sizing like the cross-venue scanner (single venue). `max_hold_s` set. Cooldown applies.
- `basis_bps -> float | None`, `on_quote(quote, book, portfolio) -> list[Signal]`.

## risk — `risk.py`

`RiskDecision(approved: bool, size: float, reason: str)` (frozen dataclass).
`RiskManager(cfg: BotConfig, portfolio: Portfolio, clock: Clock)`
- `on_quote(quote)`: liquidity gate. A (venue, symbol) whose
  `quote.depth_notional() < min_top_depth_notional` is blocked immediately; it
  re-opens only after depth stays >= the floor for `liquidity_recovery_s`.
- `on_feed_status(status)`: a disconnected venue is untradable until it reconnects.
- `tradable(venue, symbol) -> bool`.
- `check(signal, book, *, open_positions=0) -> RiskDecision`, rejecting with these reason codes:
  `halted:<why>`, `rate_limit`, `no_quote:<venue>`, `stale_quote:<venue>`,
  `low_liquidity:<venue>`, `edge_gone` (cross-venue edge recomputed from the
  CURRENT fresh quotes no longer clears the threshold), `max_open_positions`,
  `exposure_limit`, `insufficient_inventory:<venue>`, `below_min_notional`.
  A venue whose feed reported a disconnect is `stale_quote:<venue>` while its
  quote is still in the book (`no_quote:<venue>` once the book dropped it).
  Approved decisions carry `reason="ok"`.
  Approved size = min(signal.size, max_order_notional / price, inventory,
  remaining net-exposure headroom / price), floored to lot sizes. Inventory is
  `portfolio.sellable` / `buying_power`, i.e. net of reservations for open
  positions. `below_min_notional` uses the price each leg's order carries: the
  ask for a BUY, `bid * (1 - max_slippage_bps/1e4)` for a SELL (venues check
  the notional at the limit price).
- `on_execution(report)`: realized PnL into a UTC-day bucket (rolls over by
  clock); a cross-venue `FLATTENED` (no `position_id`) increments consecutive
  hedge failures (a directional partial exit does not: it is a retry bounded
  by the monitor's `max_exit_attempts`), `COMPLETED` / `OPENED` / `CLOSED`
  reset it, `NO_FILL` leaves it; `RESIDUAL` / `UNKNOWN` trip immediately;
  daily PnL <= -daily_loss_limit trips; consecutive failures >= limit trips;
  reports with fills count toward `max_trades_per_minute`.
- `net_exposure_notional(book) -> float`: sum over base assets of
  `|portfolio.net_base_change(asset)| * mid`.
- `trip(reason)`, `halted`, `halt_reason`, `reset()`, `daily_pnl`.

## execution — `execution/paper.py`, `execution/engine.py`, `execution/monitor.py`, `execution/binance_live.py`

`PaperExchange(venue: VenueConfig, book_at: Callable[[str, float], Quote | None],
clock: Clock, *, sleep_until: Callable[[float], Awaitable[None]], fill_ratio=1.0,
portfolio: Portfolio | None = None)`
implements `ExchangeClient`. `place_ioc(req)`:
```
sent = clock.now(); await asyncio.sleep(0)       # let concurrent legs read the same send time
arrival = sent + venue.latency_ms / 1000
await sleep_until(arrival)                        # live: real sleep; backtest: SimClock.set(max(now, arrival))
q = book_at(req.symbol, arrival)                  # book as of ARRIVAL, never as of the signal
```
BUY fills iff `q.ask <= limit` at `min(qty, q.ask_size * fill_ratio - taken)`
floored to lot, where `taken` is what earlier orders already filled against
the SAME quote (displayed liquidity is consumed until a newer quote replaces
it); price = `min(q.ask * (1 + slippage_bps/1e4), limit)`. SELL mirrored.
Remainder expires (IOC). Fee = `filled * price * taker_fee_bps / 1e4`. No/invalid
quote -> EXPIRED. Like the venue, it REJECTS (unstored) an order with
`qty * limit < min_notional` ("Filter failure: NOTIONAL") and, with a
`portfolio`, one the venue's balance cannot cover (SELL: base; BUY:
`qty * limit` quote). Results are stored for `query_order`. Never changes the
Portfolio (it only reads balances).

`ExecutionEngine(cfg, clients: Mapping[str, ExchangeClient], portfolio, book, clock, *, client_id_prefix="arb")`
- `async send(req) -> OrderResult`: `asyncio.wait_for(place_ioc, leg_timeout)`; on
  timeout/`ExchangeError` reconcile with `query_order`; if still unknown return
  `OrderStatus.UNKNOWN`. Applies any fill to the portfolio. Single place fills are applied.
- `async execute(signal, size) -> ExecutionReport` (CROSS_VENUE):
  1. qty = size floored to both venues' lots; limits = quote ± `max_slippage_bps`, tick-quantized.
  2. Send both legs concurrently.
  3. Any UNKNOWN -> outcome UNKNOWN (kill switch). Equal fills -> COMPLETED (both 0 -> NO_FILL).
  4. Unequal: excess long -> SELL the excess; excess short -> BUY it back. First (if
     `hedge_retry`) on the hedge venue at its current price, then unwind on the
     origin venue; limits never beyond `unwind_slippage_bps` from the leg's
     entry price. An order below the venue's lot or `min_notional` is not
     sent. Flat -> FLATTENED; only dust left (unsendable on both venues even
     at the band edge) -> FLATTENED with a dust note; still unequal -> RESIDUAL.
  5. `realized_pnl = sells - buys - fees`, with any residual marked at mid; `hedged_qty`, `residual_qty` set.
- Fills that pay part of the commission in base (`OrderResult.base_fee`, base
  units, included in `fee`) are applied as such (`Portfolio.apply_base_fee`).
  Hedging compares traded quantities: a base commission is a fee, not an
  unequal fill.
- `async enter(signal, size) -> tuple[ExecutionReport, Position | None]` (REFERENCE_LAG):
  one IOC; filled -> `OPENED` report + Position(stop, target, max_hold_s) for
  what the account received (`filled - base_fee` for a BUY).
- `async exit_position(position, reason, quote) -> ExecutionReport`: IOC for the
  open qty on the opposite side, limit = `quote` price ∓ `unwind_slippage_bps`
  (crosses to get out; a SELL limit is raised toward the bid when that clears
  `min_notional`). Partial -> reduce `position.qty`, `exit_attempts += 1`,
  outcome FLATTENED-style partial note; fully closed -> `CLOSED` with
  realized PnL net of entry+exit fees for the closed qty. If what is open
  (before or after the fill) cannot be sent (below the lot or min notional):
  `CLOSED` with a dust note and `residual_qty` = the dust, which the position
  keeps for accounting.

`PositionMonitor(cfg, engine, clock, *, max_exit_attempts=5)`
- `open(position)`, `positions`, `async on_quote(quote) -> list[ExecutionReport]`,
  `async on_tick(book) -> list[ExecutionReport]` (time stops without new quotes).
  Long: exit when `bid <= stop` ("stop"), `bid >= target` ("target"), or held >=
  `max_hold_s` ("time"). Short mirrored with `ask`. Positions still open after
  `max_exit_attempts` produce a `RESIDUAL` report. A position the engine
  CLOSED with dust left goes to `dust` (not managed, not a kill-switch event).

`BinanceSpotClient(venue: VenueConfig, api_key, api_secret, *, base_url=TESTNET_URL,
allow_mainnet=False, transport=None, clock=WallClock(), recv_window_ms=5000)`
implements `ExchangeClient` over signed REST (`POST /api/v3/order` LIMIT/IOC,
`GET /api/v3/order` by `origClientOrderId`). Testnet by default; mainnet only
with `allow_mainnet=True`. HTTP 4xx with a Binance error body -> REJECTED; 5xx,
timeouts and connection errors -> `ExchangeError` (state unknown). Decimal
formatting without exponents. Injectable `transport` for tests. A commission
taken in the base asset is reported as `base_fee` (Binance deducts it from
the base received on a BUY); a reconciled BUY (no fills in the response) is
assumed to have paid it in base. Credentials with whitespace or control
characters are refused; foreign transport exceptions are reported by type only.

## integration — `app.py`, `backtest.py`, `alerts.py`, `cli.py`

`Bot(cfg, *, clients, clock, journal, portfolio, inline_execution: bool,
execution_book=None)` wires everything per the data-flow diagram;
`async handle_event(ev)`; `async run(feeds, stop_event)`. At most one
in-flight execution per symbol; with `inline_execution` the same gate is
applied in simulated time (a signal from a quote received before its symbol's
last execution finished is `in_flight`). A filled position is handed to the
monitor before its report is recorded; an execution task that raises trips
the kill switch (`internal_error`) and is alerted. Journal writes go through
a wrapper that never raises (see invariant 9). `record_start(extra)` writes
the `start` record; shutdown writes `shutdown` (with any `dust_positions`).
`run_backtest(cfg, quotes, *, journal=None, journal_meta=None) -> BacktestResult`
replays through `Bot(inline_execution=True)` with `SimClock` and per-venue
`PaperExchange` (`book_at = history.as_of`, balance-checked against the
portfolio); the replay loop sets the clock to `max(event.ts_local,
clock.now())` because executions advance simulated time. While an execution
advances it, the engine prices from `execution_book` = the newest recorded
quote received by `clock.now()` (never a later one). Before each event, a
tick runs at every open position's time-stop time that falls before it (live
ticks every `tick_interval_s`). A `seq` that goes backwards on a
venue/symbol gets the live feed's resync (`FeedStatus` down/up). The journal
is bracketed by `start` (with `journal_meta`) and `shutdown`; the result
reports `dropped_quotes` and `seq_resets`.
`WebhookAlerter` gives each delivery a hard total deadline of `timeout_s`
(urllib's timeout is per socket read) and logs at ERROR every alert `close`
could not deliver.
CLI: `arbbot scan | paper | live | record | backtest | synth`. Live
credentials are stripped of surrounding whitespace and refused if they still
contain whitespace or control characters; `backtest --journal` appends a
bracketed run.
