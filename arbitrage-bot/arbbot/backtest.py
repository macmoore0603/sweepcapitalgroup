"""Replay recorded quotes through the real bot with simulated time and paper fills.

``run_backtest`` drives the same ``Bot`` used live (``inline_execution=True``)
with a ``SimClock`` and one ``PaperExchange`` per venue whose book is
``QuoteHistory.as_of``: an order is filled from the quote standing when it
ARRIVES (send time + venue latency), never from the quote that fired the
signal. Executions advance simulated time, so the replay loop sets the clock
to ``max(event.ts_local, clock.now())``.

The replay keeps the live bot's timing where an inline replay would differ:

* While an execution advances simulated time, the replay is paused, so the
  bot's book still shows the signal's time. The engine prices hedges,
  unwinds, exits and residual marks from the newest quote received by then
  (``ts_local <= clock.now()``, never a later one), as the live book would.
* A signal from a quote received while its symbol was still executing is
  rejected ``in_flight``, as live (the bot applies this in simulated time).
* The live bot ticks every ``tick_interval_s``; here a tick runs at each open
  position's time-stop time when no event comes before it, so a time stop
  across a gap in the data fires on time, priced from the book then.
* A venue sequence number that goes backwards (a reconnect inside the
  recording, or two recordings appended) gets the same resync the live feed
  emits (``FeedStatus`` down/up), so the newer quotes are not dropped.
* Paper fills consume displayed liquidity, enforce ``min_notional`` and
  refuse orders the venue's balance cannot cover (``PaperExchange``).

A journal gets a ``start`` record (with ``journal_meta``) and a ``shutdown``
record around the run; ids restart at 1 in every run.

Accounting (all money in quote currency; different quote currencies such as
USDT and USD are summed at par and also broken out in ``pnl_by_quote``):

* ``net_pnl`` is the sum of every report's ``realized_pnl``: fees included,
  and any residual marked at the mid when its report was written.
* ``residual_mtm`` revalues what is still not flat at the end (cross-venue
  residuals, open or abandoned directional positions) from the value already
  booked for it to the final marks.
* Equity is every balance marked at mid: one price per base asset (mean of
  the latest mid on every venue quoting it), quote currencies at 1.
  ``final_equity - initial_equity`` (both at the final marks) must equal
  ``net_pnl + residual_mtm``; ``reconciliation_error`` is the difference.
  It is computed from balances on one side and from reported orders and open
  inventory on the other, so it is zero only if every fill the portfolio saw
  was reported exactly once.
* ``equity_curve`` points carry ``pnl`` = equity minus the starting balances
  at the same marks, i.e. the strategy's effect without the price drift of
  the starting inventory; ``max_drawdown`` is measured on it.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .alerts import NullAlerter
from .app import Bot, portfolio_from_config
from .clock import SimClock
from .config import BotConfig
from .execution.paper import BookAt, PaperExchange, simclock_sleep_until
from .feeds.base import QuoteBook
from .feeds.replay import QuoteHistory
from .journal import Journal, to_jsonable
from .models import (
    ExecutionOutcome,
    ExecutionReport,
    FeedStatus,
    OrderResult,
    Position,
    Quote,
    SignalKind,
    split_symbol,
)
from .portfolio import Portfolio


@dataclass(frozen=True, slots=True)
class EquityPoint:
    ts: float
    equity: float  # every balance marked at the mids current at ``ts``
    pnl: float  # ``equity`` minus the starting balances marked at the same mids


@dataclass(slots=True)
class BacktestResult:
    """Everything a run produced. Holds no ids, so two runs of the same input compare equal."""

    events: int  # quotes replayed
    skipped_events: int  # quotes for venues/symbols not in the config
    dropped_quotes: int  # replayed quotes the bot's book refused (out of order or invalid)
    seq_resets: int  # venue sequence numbers that went backwards (resynced like the live feed does)
    start_ts: float | None
    end_ts: float | None
    signals: int
    approved: int
    rejections: dict[str, int]  # risk reason -> count
    outcomes: dict[str, int]  # execution outcome -> count (entries, exits and monitor reports)
    trades: int  # signals that got at least one fill
    closed_trades: int  # traded signals that ended flat (no residual, no open position)
    hit_rate: float | None  # closed trades with realized PnL > 0 / closed trades
    gross_pnl: float  # realized, before fees
    fees: float  # every fee paid, including entry fees of positions still open
    net_pnl: float  # sum of report.realized_pnl
    residual_mtm: float
    initial_equity: float  # starting balances at the final marks
    final_equity: float  # ending balances at the final marks
    reconciliation_error: float  # (final - initial) - (net_pnl + residual_mtm)
    max_drawdown: float  # largest peak-to-trough fall of the equity curve's pnl
    mean_signal_net_edge_bps: float | None  # over closed trades: what the scanner promised
    mean_realized_edge_bps: float | None  # over closed trades: realized PnL / traded notional
    pnl_by_quote: dict[str, float]  # net_pnl split by the quote currency of each signal's symbol
    residual_inventory: dict[str, float]  # base asset -> qty still not flat at the end
    open_positions: int
    halted: bool
    halt_reason: str | None
    scanner: dict[str, Any]
    reference_lag: dict[str, Any] | None
    final_marks: dict[str, float]  # asset -> price used for the final equity
    final_portfolio: dict[str, dict[str, float]]
    equity_curve: list[EquityPoint] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = to_jsonable(self)
        d["equity_curve"] = [[p.ts, p.equity, p.pnl] for p in self.equity_curve]
        return d

    def format_report(self) -> str:
        return format_report(self)


# --------------------------------------------------------------------------- marks


class _Marks:
    """Latest mid per configured (venue, symbol) and the prices they imply."""

    def __init__(self, cfg: BotConfig) -> None:
        self._mid: dict[tuple[str, str], float] = {}
        self._base_of = {s: split_symbol(s)[0] for s in cfg.symbols()}
        self._quotes = {split_symbol(s)[1] for s in cfg.symbols()}

    def update(self, q: Quote) -> None:
        if q.is_valid():
            self._mid[(q.venue, q.symbol)] = q.mid

    def prices(self) -> dict[str, float]:
        """One price per base asset (mean mid over every venue/symbol quoting it); quote currencies at 1."""
        sums: dict[str, list[float]] = {}
        for (_, symbol), mid in self._mid.items():
            sums.setdefault(self._base_of[symbol], []).append(mid)
        prices = {a: 1.0 for a in self._quotes}
        prices.update({base: sum(mids) / len(mids) for base, mids in sums.items()})
        return prices


def _equity(balances: Mapping[str, Mapping[str, float]], prices: Mapping[str, float]) -> float:
    return sum(qty * prices.get(asset, 0.0) for assets in balances.values() for asset, qty in assets.items())


# --------------------------------------------------------------------------- run


def _book_at(history: QuoteHistory, venue: str) -> BookAt:
    return lambda symbol, t: history.as_of(venue, symbol, t)


class _ReplayBook:
    """The book the execution engine prices from: the bot's book, or a newer quote received by now.

    The replay is paused while an execution advances simulated time; live, the
    book keeps updating meanwhile. A recorded quote with ``ts_local <=
    clock.now()`` had been received, so it is used when it is newer than the
    bot's own (and in sequence); a quote from after ``now`` never is.
    """

    def __init__(self, book: QuoteBook, history: QuoteHistory, clock: SimClock) -> None:
        self._book = book
        self._history = history
        self._clock = clock

    def get(self, venue: str, symbol: str) -> Quote | None:
        live = self._book.get(venue, symbol)
        rec = self._history.as_of(venue, symbol, self._clock.now())
        if rec is None or rec is live or not rec.is_valid():
            return live
        if live is not None and (rec.ts_local <= live.ts_local
                                 or (rec.seq is not None and live.seq is not None and rec.seq <= live.seq)):
            return live
        return rec


async def _time_stops_due(bot: Bot, clock: SimClock, until: float) -> bool:
    """Tick at each open position's time-stop time that falls before ``until``; True if any tick ran.

    Live, the bot ticks every ``tick_interval_s`` whether or not quotes arrive.
    Positions already exiting are left alone: the monitor retries them on a newer quote.
    """
    monitor = bot.monitor
    assert monitor is not None
    ticked: set[str] = set()
    ran = False
    while True:
        due = sorted((p.opened_ts + p.max_hold_s, p.id) for p in monitor.positions
                     if monitor.exiting(p.id) is None and p.id not in ticked)
        if not due or due[0][0] >= until:
            return ran
        t, pid = due[0]
        ticked.add(pid)
        clock.set(max(clock.now(), t))
        await bot.tick()
        ran = True


async def run_backtest_async(
    cfg: BotConfig,
    quotes: Iterable[Quote] | QuoteHistory,
    *,
    journal: Journal | None = None,
    curve_interval_s: float = 1.0,
    fill_ratio: float = 1.0,
    journal_meta: Mapping[str, Any] | None = None,
) -> BacktestResult:
    """``run_backtest`` for callers already inside an event loop."""
    history = quotes if isinstance(quotes, QuoteHistory) else QuoteHistory(quotes)
    configured = {(v.name, i.symbol) for v in cfg.venues for i in v.instruments}
    events = [q for q in history.events() if (q.venue, q.symbol) in configured]
    skipped = len(history) - len(events)

    clock = SimClock(events[0].ts_local if events else 0.0)
    portfolio = portfolio_from_config(cfg)
    initial = portfolio.snapshot()
    sleep_until = simclock_sleep_until(clock)
    clients = {
        v.name: PaperExchange(v, _book_at(history, v.name), clock, sleep_until=sleep_until, fill_ratio=fill_ratio,
                              portfolio=portfolio)
        for v in cfg.venues
    }
    book = QuoteBook()
    bot = Bot(
        cfg, clients=clients, clock=clock, journal=journal, portfolio=portfolio, book=book,
        inline_execution=True, alerter=NullAlerter(), keep_history=True, label="backtest",
        execution_book=_ReplayBook(book, history, clock),
    )
    assert bot.history is not None and bot.monitor is not None
    bot.record_start({
        "events": len(events),
        "data_start": events[0].ts_local if events else None,
        "data_end": events[-1].ts_local if events else None,
        **dict(journal_meta or {}),
    })
    marks = _Marks(cfg)
    curve: list[EquityPoint] = []
    last_sample = -math.inf
    sampled_reports = 0

    def sample() -> None:
        prices = marks.prices()
        eq = _equity(portfolio.snapshot(), prices)
        curve.append(EquityPoint(clock.now(), eq, eq - _equity(initial, prices)))

    last_seq: dict[tuple[str, str], int] = {}
    seq_resets = 0
    for q in events:
        ticked = bool(bot.monitor.positions) and await _time_stops_due(bot, clock, q.ts_local)
        if ticked and len(bot.history.reports) != sampled_reports:
            sample()
            last_sample, sampled_reports = clock.now(), len(bot.history.reports)
        clock.set(max(q.ts_local, clock.now()))
        if q.seq is not None:
            key = (q.venue, q.symbol)
            prev = last_seq.get(key)
            if prev is not None and q.seq < prev:  # what ws.WebSocketFeed does live on a sequence reset
                seq_resets += 1
                await bot.handle_event(FeedStatus(q.venue, False, clock.now(), f"seq_reset {q.symbol} {prev}->{q.seq}"))
                await bot.handle_event(FeedStatus(q.venue, True, clock.now(), "resync"))
            last_seq[key] = q.seq
        marks.update(q)
        await bot.handle_event(q)
        if bot.monitor.positions:
            await bot.tick()
        n_reports = len(bot.history.reports)
        if n_reports != sampled_reports or clock.now() - last_sample >= curve_interval_s:
            sample()
            last_sample, sampled_reports = clock.now(), n_reports
    if events:
        sample()
    bot._report_leftovers()  # the journal's "shutdown" record (alerts go to the NullAlerter)
    return _summarize(cfg, bot, portfolio, initial, marks.prices(), curve, len(events), skipped,
                      events[0].ts_local if events else None, events[-1].ts_local if events else None,
                      seq_resets)


def run_backtest(
    cfg: BotConfig,
    quotes: Iterable[Quote] | QuoteHistory,
    *,
    journal: Journal | None = None,
    curve_interval_s: float = 1.0,
    fill_ratio: float = 1.0,
    journal_meta: Mapping[str, Any] | None = None,
) -> BacktestResult:
    """Replay ``quotes`` through ``Bot(inline_execution=True)`` with paper fills; deterministic."""
    return asyncio.run(run_backtest_async(
        cfg, quotes, journal=journal, curve_interval_s=curve_interval_s, fill_ratio=fill_ratio,
        journal_meta=journal_meta,
    ))


# --------------------------------------------------------------------------- accounting


def _cash(orders: Iterable[OrderResult]) -> float:
    """Quote currency received minus paid, fees included: sells - buys - fees."""
    return sum(-o.side.sign * o.filled_qty * o.avg_price - o.fee for o in orders if o.filled_qty > 0)


def _position_carry(pos: Position) -> tuple[float, float]:
    """(signed qty, value already booked) for a position whose remainder is not yet realized.

    Its entry cost and remaining entry fee are carried, not realized (the
    engine books the entry fee pro rata as the position closes).
    """
    signed = pos.side.sign * pos.qty
    return signed, signed * pos.entry_price + pos.entry_fee


def _summarize(
    cfg: BotConfig,
    bot: Bot,
    portfolio: Portfolio,
    initial: Mapping[str, Mapping[str, float]],
    prices: Mapping[str, float],
    curve: list[EquityPoint],
    events: int,
    skipped: int,
    start_ts: float | None,
    end_ts: float | None,
    seq_resets: int = 0,
) -> BacktestResult:
    assert bot.history is not None and bot.monitor is not None
    hist, monitor = bot.history, bot.monitor
    kind_of = {s.id: s for s in hist.signals}
    reports_of: dict[str, list[ExecutionReport]] = {}
    for r in hist.reports:
        reports_of.setdefault(r.signal_id, []).append(r)

    net = sum(r.realized_pnl for r in hist.reports)
    fees = sum(o.fee for r in hist.reports for o in r.orders)

    # Inventory still not flat, with the value realized PnL already booked for it.
    inventory: dict[str, float] = {}
    booked = 0.0
    for r in hist.reports:
        sig = kind_of.get(r.signal_id)
        if sig is None or sig.kind is not SignalKind.CROSS_VENUE:
            continue
        # A cross-venue report books cash plus its residual at the mid it was marked at.
        booked += r.realized_pnl - _cash(r.orders)
        if r.residual_qty:
            base = split_symbol(sig.symbol)[0]
            inventory[base] = inventory.get(base, 0.0) + r.residual_qty
    deferred_fees = 0.0
    carried_positions = [*monitor.positions, *monitor.unresolved]
    for pos in carried_positions:
        signed, value = _position_carry(pos)
        booked += value
        deferred_fees += pos.entry_fee
        base = split_symbol(pos.symbol)[0]
        inventory[base] = inventory.get(base, 0.0) + signed
    for pos in monitor.dust:
        # Closed as dust: the unsellable remainder is still held, carried at cost like an open position.
        signed, value = _position_carry(pos)
        booked += value
        deferred_fees += pos.entry_fee
        base = split_symbol(pos.symbol)[0]
        inventory[base] = inventory.get(base, 0.0) + signed
    for pos in monitor.residuals:
        # The monitor's RESIDUAL report realized the remainder at the mid of the time.
        signed, value = _position_carry(pos)
        residual_report = next(r for r in reversed(reports_of[pos.signal_id])
                               if r.position_id == pos.id and r.outcome is ExecutionOutcome.RESIDUAL)
        booked += value + residual_report.realized_pnl
        base = split_symbol(pos.symbol)[0]
        inventory[base] = inventory.get(base, 0.0) + signed
    residual_mtm = sum(qty * prices.get(asset, 0.0) for asset, qty in inventory.items()) - booked

    initial_equity = _equity(initial, prices)
    final_equity = _equity(portfolio.snapshot(), prices)
    reconciliation_error = (final_equity - initial_equity) - (net + residual_mtm)

    # Per-signal trade statistics (closed trades only: nothing of theirs left open).
    # Not closed: positions still open/unresolved/abandoned, and arbs that left a residual.
    still_open = {p.signal_id for p in (*carried_positions, *monitor.residuals)}
    still_open |= {sid for sid, reports in reports_of.items() if any(r.residual_qty for r in reports
                   if r.position_id is None)}
    trades = closed = wins = 0
    sig_edges: list[float] = []
    real_edges: list[float] = []
    pnl_by_quote: dict[str, float] = {}
    for sid, reports in reports_of.items():
        sig = kind_of.get(sid)
        pnl = sum(r.realized_pnl for r in reports)
        if sig is not None:
            quote_ccy = split_symbol(sig.symbol)[1]
            pnl_by_quote[quote_ccy] = pnl_by_quote.get(quote_ccy, 0.0) + pnl
        orders = [o for r in reports for o in r.orders if o.filled_qty > 0]
        if not orders or sig is None:
            continue
        trades += 1
        if sid in still_open:
            continue
        closed += 1
        wins += pnl > 0
        notional = max(
            sum(o.notional for o in orders if o.side.sign > 0),
            sum(o.notional for o in orders if o.side.sign < 0),
        )
        sig_edges.append(sig.net_edge_bps)
        real_edges.append(pnl / notional * 1e4)

    rejections: dict[str, int] = {}
    for _, d in hist.decisions:
        if not d.approved:
            rejections[d.reason] = rejections.get(d.reason, 0) + 1

    peak, max_dd = 0.0, 0.0
    for p in curve:
        peak = max(peak, p.pnl)
        max_dd = max(max_dd, peak - p.pnl)

    return BacktestResult(
        events=events,
        skipped_events=skipped,
        dropped_quotes=bot.counters.dropped_quotes,
        seq_resets=seq_resets,
        start_ts=start_ts,
        end_ts=end_ts,
        signals=len(hist.signals),
        approved=sum(1 for _, d in hist.decisions if d.approved),
        rejections=dict(sorted(rejections.items())),
        outcomes=dict(sorted(bot.counters.outcomes.items())),
        trades=trades,
        closed_trades=closed,
        hit_rate=wins / closed if closed else None,
        gross_pnl=net + fees - deferred_fees,
        fees=fees,
        net_pnl=net,
        residual_mtm=residual_mtm,
        initial_equity=initial_equity,
        final_equity=final_equity,
        reconciliation_error=reconciliation_error,
        max_drawdown=max_dd,
        mean_signal_net_edge_bps=sum(sig_edges) / len(sig_edges) if sig_edges else None,
        mean_realized_edge_bps=sum(real_edges) / len(real_edges) if real_edges else None,
        pnl_by_quote=dict(sorted(pnl_by_quote.items())),
        residual_inventory={a: q for a, q in sorted(inventory.items()) if q},
        open_positions=len(monitor.positions),
        halted=bot.risk.halted,
        halt_reason=bot.risk.halt_reason,
        scanner=bot.scanner.stats.summary(),
        reference_lag=bot.lag_scanner.stats.summary() if bot.lag_scanner is not None else None,
        final_marks=dict(sorted(prices.items())),
        final_portfolio={v: dict(sorted(a.items())) for v, a in sorted(portfolio.snapshot().items())},
        equity_curve=curve,
    )


# --------------------------------------------------------------------------- report


def _ts(t: float | None) -> str:
    if t is None:
        return "-"
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "Z"


def _counts(d: Mapping[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))) or "none"


def _bps(x: float | None) -> str:
    return "-" if x is None else f"{x:+.2f} bps"


def format_report(r: BacktestResult) -> str:
    """Human-readable summary (money in quote currency; USD-like quotes summed at par)."""
    span = (r.end_ts - r.start_ts) if r.start_ts is not None and r.end_ts is not None else 0.0
    lines = [
        "Backtest",
        f"  data        {r.events:,} quotes over {span:,.1f}s ({_ts(r.start_ts)} -> {_ts(r.end_ts)})"
        + (f"; {r.skipped_events:,} skipped (not in config)" if r.skipped_events else "")
        + (f"; {r.dropped_quotes:,} dropped (out of order or invalid)" if r.dropped_quotes else "")
        + (f"; {r.seq_resets:,} sequence resets (resynced)" if r.seq_resets else ""),
        f"  signals     {r.signals:,} emitted, {r.approved:,} approved by risk",
        f"  rejections  {_counts(r.rejections)}",
        f"  outcomes    {_counts(r.outcomes)}",
        f"  trades      {r.trades:,} with fills, {r.closed_trades:,} closed, hit rate "
        + ("-" if r.hit_rate is None else f"{r.hit_rate:.1%}"),
        (f"  edge        signal net {_bps(r.mean_signal_net_edge_bps)} vs realized "
         f"{_bps(r.mean_realized_edge_bps)} (mean over closed trades)"),
        (f"  pnl         gross {r.gross_pnl:+,.4f}  fees {r.fees:,.4f}  net {r.net_pnl:+,.4f}"
         f"  residual MTM {r.residual_mtm:+,.4f}"),
    ]
    if len(r.pnl_by_quote) > 1:
        lines.append("  by quote    " + ", ".join(f"{k} {v:+,.4f}" for k, v in r.pnl_by_quote.items()))
    lines += [
        (f"  equity      {r.initial_equity:,.4f} -> {r.final_equity:,.4f} at final mids"
         f" (change {r.final_equity - r.initial_equity:+,.4f}; reconciliation error {r.reconciliation_error:.2e})"),
        f"  drawdown    {r.max_drawdown:,.4f} (max peak-to-trough of strategy PnL marked at mid)",
    ]
    if r.residual_inventory or r.open_positions:
        lines.append(f"  not flat    {r.residual_inventory} ({r.open_positions} open position(s))")
    lines.append("  kill switch " + (f"TRIPPED: {r.halt_reason}" if r.halted else "not tripped"))
    s = r.scanner
    best_g, best_n = s.get("best_gross_bps"), s.get("best_net_bps")
    lines.append(
        f"  scanner     {s.get('evaluations', 0):,} pair evaluations, {s.get('candidates', 0):,} candidates; "
        f"best gross {_bps(best_g)}, best net {_bps(best_n)}"  # type: ignore[arg-type]
    )
    net_hist = {k: v for k, v in dict(s.get("net_edge_bps", {})).items() if v}
    if net_hist:
        lines.append("  net edge    " + ", ".join(f"{k}: {v}" for k, v in net_hist.items())
                     + "  (best net edge per quote update, bps)")
    if r.reference_lag is not None:
        lag = r.reference_lag
        lines.append(f"  ref lag     {lag.get('evaluations', 0):,} evaluations, {lag.get('emitted', 0):,} signals")
    return "\n".join(lines)


__all__ = [
    "BacktestResult",
    "EquityPoint",
    "format_report",
    "run_backtest",
    "run_backtest_async",
]

