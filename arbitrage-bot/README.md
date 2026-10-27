# arbbot

A cross-venue crypto arbitrage scanner and execution engine for spot markets.
It streams top-of-book quotes from several venues over websockets (Binance,
Bybit, Kraken, Coinbase; an OKX adapter is built from its docs but untested
live). When the same instrument can be bought on one venue and sold on another
for more than both legs' taker fees + slippage + a safety margin X, it emits a
signal. The signal passes hard risk limits and is then executed as two
simultaneous IOC limit orders. Unequal fills are hedged or unwound at once.
An optional *reference-lag* strategy (a directional trade on a venue that lags
another; disabled by default) is also included.

It runs in five modes: `scan` (signals only), `paper` (simulated fills against
the live book), `live` (real orders; Binance spot only, testnet by default,
heavily gated), plus `record` and `backtest` for replaying real data through
the exact same code.

## Read this first

- **The viral "$68 → $750k" arbitrage-bot story is self-reported and
  unverified.** Nothing in this repository reproduces it, and you should not
  expect it to.
- **At retail fee tiers, cross-venue BTC spreads are usually far below
  round-trip taker costs.** Binance + Bybit at entry-tier fees cost about 22 bps
  per arb (see below). In 30 minutes of recorded live data on 2026-10-27
  (426k quotes; BTC-USDT and ETH-USDT on Binance + Bybit, BTC-USD on Kraken +
  Coinbase), the backtest with `config.example.toml` produced **0 signals**:
  the widest gross gap between Binance and Bybit was **+4.91 bps** (median
  0.30, 99th percentile 1.38), against those 22 bps of cost. Re-running the
  same data at **zero** fees, a 0.5 bp margin and no liquidity floor still lost
  money at 50 ms latency: signals averaged +0.65 bps of net edge, but fills
  realized −0.27 bps because the gaps closed before the orders arrived. Seven
  of 22 trades filled unequally, and the kill switch stopped it. The edge here
  is latency and fee tier, not code. Expect backtests on real recorded data to
  show **few or no profitable trades**. The synthetic data generator injects
  40 bps dislocations so the demo has something to trade. Its results are not
  evidence of a real edge.
- Real arbitrage also faces costs this code does not model: moving inventory
  between venues (withdrawal fees and delays), venue outages, rate limits,
  depth beyond the top of book, latency jitter, account limits and taxes.
- **Not financial advice. Only risk money you can afford to lose.**

## Architecture

```
 venue websockets ─► feeds/venues.py (per-venue adapter: url, subscribe, parse)
                     feeds/ws.py WebSocketFeed (reconnect, backoff, stall/seq-reset detection)
        │
        ▼ merge_feeds (bounded fan-in)
 app.py Bot.handle_event(event)
        │  QuoteBook.update            (disconnect ─► invalidate_venue)
        │  RiskManager.on_quote / on_feed_status      liquidity + connectivity gate
        │  PositionMonitor.on_quote                   exits FIRST: stops, targets, time stops
        ▼
 signal.py   CrossVenueScanner / ReferenceLagScanner ─► Signal ─────────► journal "signal"
        ▼
 risk.py     RiskManager.check ─► RiskDecision (approved size, or reason) ─► journal "risk"
        ▼
 execution/  ExecutionEngine.execute (two legs + hedge/unwind) / enter (directional)
             ├─ PaperExchange      paper + backtest: fills from the book at ORDER ARRIVAL time
             └─ BinanceSpotClient  live: signed REST, LIMIT IOC
        ▼
 ExecutionReport ─► RiskManager.on_execution (PnL, kill switch) ─► journal "execution"
                    alerts.py webhook on kill switch / RESIDUAL / UNKNOWN ─► journal "halt"
```

`backtest.py` feeds recorded quotes through the same `Bot` with a simulated
clock and a `PaperExchange` per venue. Each order sees the book as it stood
when the order *arrived* (send time + `latency_ms`), never the book that fired
the signal. It also keeps the live bot's timing: hedges, unwinds and marks are
priced from the newest quote received by the time they are sent; a signal
from a quote received while its symbol is still executing is rejected
`in_flight`; time stops fire at their due time even across a gap in the data;
and a venue sequence number that goes backwards (a reconnect inside a
recording) is resynced as the live feed does, not dropped.

| Module | Role |
| --- | --- |
| `models.py`, `config.py`, `portfolio.py`, `clock.py`, `mathutil.py`, `journal.py` | shared types, validated TOML config, balances, injectable clock, exchange-grid rounding, JSONL journal |
| `feeds/` | venue adapters, reconnecting websocket feed, recorder, replay + synthetic data |
| `signal.py` | cross-venue and reference-lag scanners, edge histograms |
| `risk.py` | pre-trade checks, liquidity gate, PnL buckets, kill switch |
| `execution/` | engine (hedge/unwind), position monitor, paper exchange, Binance spot client |
| `app.py`, `backtest.py`, `alerts.py`, `cli.py` | wiring, replay, alerts, command line |

## Quickstart

Python 3.11+.

```bash
cd arbitrage-bot
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp config.example.toml config.toml        # then put YOUR fee tier and balances in it
python -m pytest -q                       # the test suite (no network needed)
```

**1. Synthetic data to backtest.** This is a demo of the mechanics only:

```bash
arbbot synth --out data/synth.jsonl       # 600 s of binance+bybit BTC-USDT with 40 bps dislocations
arbbot backtest --data data/synth.jsonl --report data/synth_report.json
```

```
Backtest
  data        12,000 quotes over 599.9s (2026-01-01 00:00:00.033Z -> 2026-01-01 00:09:59.966Z)
  signals     10 emitted, 10 approved by risk
  rejections  none
  outcomes    completed 10
  trades      10 with fills, 10 closed, hit rate 100.0%
  edge        signal net +16.86 bps vs realized +16.94 bps (mean over closed trades)
  pnl         gross +18.5167  fees 10.0156  net +8.5011  residual MTM -0.0000
  equity      29,921.9068 -> 29,930.4079 at final mids (change +8.5011; reconciliation error -2.27e-13)
  ...
```

**2. Record real quotes, then backtest them.** This is the one that matters:

```bash
arbbot record --out data/quotes.jsonl --duration 3600
arbbot backtest --data data/quotes.jsonl --report data/report.json --journal data/bt_journal.jsonl
```

The report's `net edge` histogram is the best net edge per quote update. It
shows how far the market is from your costs, and how often a given X would
have fired. `backtest` also accepts CSV with the header
`venue,symbol,bid,bid_size,ask,ask_size,ts_local[,ts_exchange,seq]`.
`--journal` appends: each run is bracketed by `start` (with the data and
config paths) and `shutdown` records, and ids restart at `sig-1` in every run.

**3. Scan live, with no orders:**

```bash
arbbot scan                    # Ctrl-C to stop; the journal goes to journal_path (logs/journal.jsonl)
```

**4. Paper trade.** These are simulated fills against the live book after
each venue's `latency_ms`:

```bash
arbbot paper --duration 3600
```

**5. Live trading** is refused unless *all* of the following hold:

- the config says `mode = "live"`;
- `ARBBOT_LIVE_CONFIRM=I_ACCEPT_THE_RISK` is set;
- every venue in the config has a live order client. **Only Binance spot is
  implemented** (`feed = "binance"`), so the example config is refused; a live
  config must contain Binance venues only;
- `ARBBOT_BINANCE_API_KEY` and `ARBBOT_BINANCE_API_SECRET` are set
  (surrounding whitespace, such as a secret file's trailing newline, is
  stripped; a value that still contains whitespace or control characters is
  refused).

Orders go to the **Binance spot testnet** (`https://testnet.binance.vision`),
priced from the testnet's own market data, unless you pass `--mainnet`. The
bot does **not** read balances from the venue: `starting_balances` must match
your account, or orders will be rejected (and hedged or unwound).

```bash
ARBBOT_LIVE_CONFIRM=I_ACCEPT_THE_RISK ARBBOT_BINANCE_API_KEY=... ARBBOT_BINANCE_API_SECRET=... \
  arbbot live -c config.live.toml
```

Exit codes: `0` ok, `1` runtime failure, `2` configuration or usage error
(this includes a refused live start).

| Environment variable | Purpose |
| --- | --- |
| `ARBBOT_ALERT_WEBHOOK` | webhook URL for alerts (POST `{"text": ...}`, the Slack incoming-webhook format). Treated as a secret and never logged. |
| `ARBBOT_LIVE_CONFIRM` | must be `I_ACCEPT_THE_RISK` for `arbbot live` |
| `ARBBOT_BINANCE_API_KEY`, `ARBBOT_BINANCE_API_SECRET` | Binance credentials (live only). Never logged, never in alerts. |

## How X relates to round-trip costs

For a cross-venue arb you buy at venue A's ask and sell at venue B's bid:

```
gross_bps = (bid_B - ask_A) / ask_A * 1e4
cost_bps  = taker_fee_A + taker_fee_B + slippage_A + slippage_B
net_bps   = gross_bps - cost_bps          signal iff net_bps >= X (min_net_edge_bps) and net_bps > 0
```

Worked example with the example config, Binance + Bybit at their entry-tier
0.10% taker fees and 1 bp of slippage each: `cost = 10 + 10 + 1 + 1 = 22 bps`.
With `X = 5`, the gross spread must be at least **27 bps**. At an ask of
80,000 USDT, Bybit's bid must be at least 80,216 (Binance's ask + $216). At
that threshold, a 500 USDT trade (0.00625 BTC, `max_order_notional`) is
expected to make about
`0.00625 × (80,216 × (1 − 0.0011) − 80,000 × (1 + 0.0011)) ≈ 0.25 USDT`.
Kraken + Coinbase at entry tier is roughly 80 + 120 + 2 = 202 bps, so with X = 5
it needs 207 bps.

X is the margin for what the cost model gets wrong: the book moving during
your latency, fills worse than the assumed slippage, fee rounding. The edge is
recomputed by the risk manager from the current quotes just before sending
(`edge_gone`). Choose X from backtests on *recorded* data, not synthetic data.
Raising your fee tier (volume, discount tokens) lowers `cost_bps`, and that
moves profitability far more than tuning X.

## Risk controls

- **Same instrument only.** BTC-USD is never compared with BTC-USDT: the two
  carry a floating basis, and that is not an arb.
- **No trading on stale data.** A quote older than `max_quote_age_ms`, or from
  a feed that reported a disconnect, is unusable. A disconnect (or a venue
  sequence reset) drops that venue's quotes from the book.
- **Liquidity gate.** A venue/symbol whose top-of-book depth is below
  `min_top_depth_notional` is blocked at once, and only re-opens after depth
  has held for `liquidity_recovery_s`. A crossed or empty book also closes it.
- **Costs before signals.** The net edge is after taker fees and expected
  slippage on every leg, plus X. Risk re-checks it on the current quotes.
- **USD-quoted symbols only.** Every money figure is in a symbol's quote
  currency and summed at par, so only USD and USD stablecoins (USDT, USDC,
  FDUSD, TUSD, USDP, DAI) are accepted as quote currencies; `ETH-BTC` or
  `BTC-EUR` is refused at load time.
- **Sizing caps.** The size is the smallest of: `participation` of the
  displayed size, `max_order_notional`, cash and inventory on each venue (fee
  and slippage included), and the remaining `max_net_exposure_notional`
  headroom. It is then floored to both venues' lot sizes and checked against
  each venue's min notional at the price each order will carry (a SELL
  leg's limit can be `max_slippage_bps` below the bid). Inventory that backs
  an open reference-lag position (the base of a long, the cash to buy back a
  short) is reserved: an arb is never sized from coins a position needs to exit.
- **Bounded entries.** Orders are IOC limits only, at most `max_slippage_bps`
  through the quote and rounded to the tick on the safe side.
- **Never a silent half-open arb.** Unequal fills are hedged on the other
  venue, then unwound on the origin. Both are capped at `unwind_slippage_bps`
  from the entry price. Anything still unhedged (RESIDUAL), or any order whose
  state is unknown (UNKNOWN), trips the kill switch and sends an alert.
  Orders a venue is certain to refuse (below its lot or `min_notional`) are
  never sent. A remainder that no order on either venue could trade, such as
  7e-6 BTC left by Binance's 1e-5 lot against Bybit's 1e-6, is *dust*: the
  arb is FLATTENED with a dust note, the dust stays in the exposure figures,
  and the kill switch is not tripped. A reference-lag position whose
  remainder cannot be sold is closed as dust the same way.
- **Directional positions** (reference lag) have a hard stop, a target and a
  time stop. Exits are never blocked by risk, keep running while the kill
  switch is tripped, and become RESIDUAL after repeated failures.
- **Kill switch.** It trips on RESIDUAL, UNKNOWN, the `daily_loss_limit` (UTC
  day), `max_consecutive_hedge_failures` (arbs whose legs filled unequally; a
  position closed in several partial exits is not a hedge failure), a failed
  journal write (`journal_error`), or an internal error (including an
  execution task that raised). Once tripped,
  every new entry is rejected (`halted:<reason>`), it is journaled and alerted,
  and only the operator clears it. The state lives in memory, so restarting the
  process *is* the reset: reconcile your venue balances first.
- **Other limits.** `max_trades_per_minute`, `max_open_positions` (reference
  lag), and at most one in-flight execution per symbol.
- **Audit trail.** The journal (JSONL) records every signal (`signal`) with
  its risk decision (`risk`, same `signal_id`), every execution report with
  its orders (`execution`), every kill-switch trip (`halt`), feed status
  changes (`feed`), and `start`/`shutdown` records. Ids are unique within a
  run (between `start` and `shutdown`). Writing the journal never strands a
  trade: if a write fails, the position is still monitored, the failure is
  alerted, and the kill switch trips.

Known limitations:

- Live mode does not reconcile balances with the venue.
- Executions for *different* symbols that share a quote currency on one venue
  can run at the same time and size from the same balance. Keep
  `max_order_notional` well below your balances.
- Coinbase's ticker channel updates on trades rather than on every
  best-bid/offer change, so its quotes can go stale in quiet markets.
- Backtests fill against the top of book only (no queue position or impact).
  An order consumes the displayed size of the quote it fills against until a
  newer quote replaces it, but deeper levels are not modelled. PnL sums USD
  and USD stablecoins at par. The model is pessimistic for hedges and
  unwinds. An IOC allowed to cross 50 bps fills only the displayed top size in
  the paper model, while on a real venue it would sweep deeper levels. So
  `paper`/`backtest` can report a RESIDUAL (and trip the kill switch) when a
  live venue would have flattened. That bias makes results look worse, never
  better. Recording L2 depth would remove it.
- Binance takes the commission from the asset received unless you pay with
  BNB: a BUY of 1 BTC credits 0.999 BTC. The bot tracks that (`base_fee`) and
  only sells what was received. For an order it had to reconcile (no fills in
  the response), it assumes the commission was paid in base, which can leave
  up to 0.1% of the position behind when you actually pay in BNB.

## Adding a venue

1. **Market data.** Subclass `VenueAdapter` in `arbbot/feeds/venues.py`:
   `url()`, `subscribe_messages()`, `heartbeat()` if the venue needs an app
   ping, and `parse()`. `parse()` returns `Quote`s, returns `[]` for
   acks/pongs/status, and raises `ValueError` for malformed or error frames.
   Implement `reset()` if the adapter keeps book state. Register it in
   `ADAPTERS`, capture a real frame into `tests/fixtures/`, and test the parse
   field by field. Verify formats against the venue's official docs.
2. **Orders (live only).** Implement the `ExchangeClient` protocol
   (`arbbot/execution/base.py`):
   - `place_ioc(req)` returns the final `OrderResult`. Venue refusals come back
     as `REJECTED`; raise `ExchangeError` when the order's fate is unknown.
   - `query_order(req)` returns `None` only if the venue has no record, and
     raises `ExchangeError` when unsure.

   `execution/binance_live.py` is the template (signing, exponent-free
   decimals, grid snapping, testnet by default, no secrets in errors). Then
   add the feed key to `LIVE_CLIENT_FEEDS` and the client to
   `build_live_clients` in `cli.py`.
3. **Config.** Add a `[[venues]]` block with tick/lot/min-notional values
   taken from the venue's instrument endpoint and *your* fee tier.

## Deployment

```bash
docker build -t arbbot .
docker run --rm -v "$PWD/config.toml:/config/config.toml:ro" -v "$PWD/logs:/app/logs" arbbot
# paper:  docker run ... arbbot paper --config /config/config.toml
docker stop -t 30 <container>      # SIGTERM: finishes in-flight orders (up to ~21 s with defaults), then exits
```

The image (`python:3.12-slim`) runs as a non-root user (uid 10001; make the
mounted `logs/` writable for it). Its default command is
`scan --config /config/config.toml`.

- **Run near the venues.** Paper and backtest fills assume each venue's
  `latency_ms`, and live profitability depends on it. Host the bot close to
  the venues' matching engines (check each venue's documentation), measure
  round-trip times from that host, and put them in the config.
- **Alerts only.** Set `ARBBOT_ALERT_WEBHOOK` to get kill-switch trips,
  RESIDUAL/UNKNOWN executions, internal errors, journal failures and unclean
  shutdowns pushed to you. Each delivery must finish within 5 s in total, so a
  slow endpoint cannot hold back a later alert; alerts still undelivered at
  shutdown are logged at ERROR level. The bot has no inbound control surface (no HTTP API, no remote
  commands), so nothing on the host needs to be exposed. You stop it with
  SIGTERM/SIGINT and act on the venues yourself.
- Keep API keys in the environment (or your orchestrator's secret store),
  never in the config file. Give them trade-only permissions with withdrawals
  disabled, and an IP allowlist.

## Venue facts used here

Checked on 2026-10-27: instrument filters from each venue's public instrument
endpoint (Bybit's REST API was geo-blocked from the checking host, so its
values come from the official docs and live websocket precision), and fees
from the official fee pages. Coinbase's fee pages could not be read, so its
120 bps is a conservative placeholder and is marked UNVERIFIED in the config.
Fee tiers change and depend on your account and region: **verify your own
tier.** See the comments in `config.example.toml` for sources.
