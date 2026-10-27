"""Order execution: two-leg arbs, directional entries/exits, and never a silent half-open arb.

Every order goes through ``ExecutionEngine.send``, which is the single place
fills are applied to the Portfolio (invariant 8). ``send`` never raises for a
venue problem: a timeout, ``ExchangeError`` or any other client exception is
reconciled with ``query_order``; an order whose fate is still unknown comes
back as ``OrderStatus.UNKNOWN`` and nothing is guessed about it.

Cross-venue (``execute``):
  1. qty = size floored to a lot both venues accept; entry limits are the
     current book quote +/- ``max_slippage_bps``, tick-quantized so they are
     never more aggressive than that (BUY rounds down, SELL rounds up).
  2. Both legs are sent concurrently.
  3. Any UNKNOWN order -> outcome UNKNOWN and no further orders (a hedge
     against a leg that may have filled could double the exposure).
     Equal fills -> COMPLETED (both zero -> NO_FILL).
  4. Unequal fills leave an excess: long (bought more than sold) is SOLD,
     short is BOUGHT back. First, if ``hedge_retry``, on the hedge venue (the
     under-filled leg's venue, completing the arb) with a limit at its current
     price +/- ``max_slippage_bps``; then the remainder is unwound on the
     origin venue (the over-filled leg's venue) with a limit crossing as far
     as allowed. Both limits are clamped to ``unwind_slippage_bps`` from the
     over-filled leg's entry (average fill) price. An order the venue is
     certain to refuse (below its lot or its ``min_notional``) is not sent.
     Flat -> FLATTENED. Still unequal, but only by *dust* that no order on
     either venue can flatten (below the lot or the min notional of both) ->
     FLATTENED with a dust note and ``residual_qty`` = the dust: it stays in
     the exposure figures but does not trip the kill switch. Otherwise -> RESIDUAL.
  5. ``realized_pnl = sells - buys - fees + residual_qty * mid`` where the
     residual is marked at the mid of the venue holding it.
     ``hedged_qty = min(total bought, total sold)``; ``residual_qty`` = bought - sold.

Directional (``enter`` / ``exit_position``): one IOC entry opens a Position
carrying the signal's stop, target and ``max_hold_s``; its qty is what the
account received (a BUY whose commission was taken in base holds
``filled - base_fee``). Exits cross by up to ``unwind_slippage_bps`` from the
exit quote. Entry fees are realized when the position is closed, pro rata per
closed qty, so the OPENED report books no PnL. A remainder no order can sell
(below the lot or the min notional) is closed as dust: CLOSED with
``residual_qty`` = the dust, which stays in the account.

Fills that pay part of the commission in base (``OrderResult.base_fee``) are
applied to the Portfolio as such. Hedging compares the traded quantities: a
commission paid in base is a fee, not an unequal fill.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import math
from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal

from ..clock import Clock
from ..config import BotConfig, InstrumentConfig, VenueConfig
from ..feeds.base import BookView
from ..mathutil import ceil_to_step, common_lot, floor_to_step, quantize_limit
from ..models import (
    ExecutionOutcome,
    ExecutionReport,
    Leg,
    OrderRequest,
    OrderResult,
    OrderStatus,
    Position,
    Quote,
    Side,
    Signal,
    SignalKind,
    next_id,
)
from ..portfolio import Portfolio
from .base import ExchangeClient, ExchangeError

log = logging.getLogger(__name__)

_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def _base36(n: int) -> str:
    out = ""
    while True:
        n, r = divmod(n, 36)
        out = _B36[r] + out
        if n == 0:
            return out


def _dec(x: float) -> Decimal:
    return Decimal(repr(x))


def _qty_sum(xs: Iterable[float]) -> float:
    """Exact sum of lot-grid quantities (0.7 - 0.4 is 0.3, not 0.29999999999999993)."""
    return float(sum((_dec(x) for x in xs), Decimal(0)))


def _floor_qty(size: float, lot: float) -> float:
    """``size`` floored to ``lot``; 0.0 for non-positive or non-finite sizes."""
    if not math.isfinite(size) or size <= 0:
        return 0.0
    return max(floor_to_step(size, lot), 0.0)


def _limit(ref: float, side: Side, bps: float, tick: float) -> float:
    """``ref`` moved ``bps`` against us (BUY up, SELL down), quantized never beyond that."""
    return quantize_limit(ref * (1 + side.sign * bps / 1e4), tick, side)


def _usable(q: Quote | None) -> Quote | None:
    return q if q is not None and q.is_valid() else None


def _notional(qty: float, price: float) -> float:
    """``qty * price`` on the decimal forms (min-notional checks at the boundary must be exact)."""
    return float(_dec(qty) * _dec(price))


def _unsendable(inst: InstrumentConfig, venue: str, qty: float, limit: float) -> str | None:
    """Why the venue would refuse ``qty`` at ``limit`` (below its lot or min notional); None if it would not."""
    if qty <= 0:
        return f"below the {venue} lot"
    if _notional(qty, limit) < inst.min_notional:
        return f"below the {venue} min notional {inst.min_notional:g}"
    return None


def _fit_sell_notional(inst: InstrumentConfig, qty: float, limit: float, bid: float) -> float:
    """A SELL limit raised (less aggressive) just enough to clear ``min_notional``, if it can still fill at ``bid``.

    Venues check the notional at the LIMIT price; an IOC sell fills at the bid
    whenever its limit is at or below it, so the limit can move up to the bid.
    """
    if qty <= 0 or _notional(qty, limit) >= inst.min_notional:
        return limit
    need = ceil_to_step(float(_dec(inst.min_notional) / _dec(qty)), inst.tick_size)
    if _notional(qty, need) < inst.min_notional:
        need = float(_dec(need) + _dec(inst.tick_size))
    return need if need <= bid else limit


class ExecutionEngine:
    """Sends orders, applies fills to the Portfolio, and hedges/unwinds unequal fills."""

    def __init__(
        self,
        cfg: BotConfig,
        clients: Mapping[str, ExchangeClient],
        portfolio: Portfolio,
        book: BookView,
        clock: Clock,
        *,
        client_id_prefix: str = "arb",
        ids: Callable[[str], str] | None = None,
    ) -> None:
        self._cfg = cfg
        self._ex = cfg.execution
        self._clients = clients
        self._portfolio = portfolio
        self._book = book
        self._clock = clock
        # Venues accept a client id again once its previous order is done (Binance
        # spot docs), so a lookup by id could hit an order from an earlier run: ids
        # carry a session stamp from the injected clock (deterministic in backtests,
        # unique per process live) and stay short, using only [a-z0-9-].
        self._id_stem = f"{client_id_prefix}-{_base36(int(clock.now() * 1000))}"
        self._seq = itertools.count(1)
        self._timeout_s = self._ex.leg_timeout_ms / 1000.0
        self._next_id = ids or next_id

    # ------------------------------------------------------------------ orders

    def new_client_id(self) -> str:
        return f"{self._id_stem}-{next(self._seq)}"

    def _instrument(self, venue: str, symbol: str) -> tuple[VenueConfig, InstrumentConfig]:
        try:
            v = self._cfg.venue(venue)
        except KeyError:
            raise ValueError(f"unknown venue {venue!r}") from None
        inst = v.instrument(symbol)
        if inst is None:
            raise ValueError(f"{symbol} is not configured on venue {venue!r}")
        return v, inst

    def _client(self, venue: str) -> ExchangeClient:
        client = self._clients.get(venue)
        if client is None:
            raise ValueError(f"no exchange client for venue {venue!r}")
        return client

    async def send(self, req: OrderRequest) -> OrderResult:
        """Place one IOC order, reconcile it if its fate is unknown, and apply any fill.

        Never raises for transport or venue errors: an order that cannot be
        reconciled comes back as ``OrderStatus.UNKNOWN`` (with ``error`` set).
        """
        client = self._client(req.venue)
        try:
            res = await asyncio.wait_for(client.place_ioc(req), self._timeout_s)
        except TimeoutError:
            res = await self._reconcile(client, req, f"timeout after {self._ex.leg_timeout_ms:g} ms")
        except ExchangeError as e:
            res = await self._reconcile(client, req, f"exchange error: {e}")
        except Exception as e:  # a client bug must not strand the other leg of an arb
            log.exception("unexpected error placing %s", req.client_id)
            res = await self._reconcile(client, req, f"{type(e).__name__}: {e}")
        else:
            if res.status is OrderStatus.UNKNOWN:
                res = await self._reconcile(client, req, f"client reported unknown state: {res.error}")
        if res.filled_qty > 0:
            self._portfolio.apply_fill(req.venue, req.symbol, req.side, res.filled_qty, res.avg_price, res.fee)
            if res.base_fee > 0:
                self._portfolio.apply_base_fee(req.venue, req.symbol, res.base_fee, res.avg_price)
        if res.status is OrderStatus.UNKNOWN:
            log.error("order %s on %s is UNKNOWN: %s", req.client_id, req.venue, res.error)
        return res

    async def _reconcile(self, client: ExchangeClient, req: OrderRequest, why: str) -> OrderResult:
        log.warning("order %s on %s: %s; reconciling", req.client_id, req.venue, why)
        try:
            found = await asyncio.wait_for(client.query_order(req), self._timeout_s)
        except Exception as e:  # any failure here leaves the order unknown
            log.warning("query for %s on %s failed", req.client_id, req.venue, exc_info=True)
            return self._unknown(req, f"{why}; query failed: {type(e).__name__}: {e}")
        if found is None:
            return self._unknown(req, f"{why}; venue has no record")
        return found

    def _unknown(self, req: OrderRequest, error: str) -> OrderResult:
        return OrderResult(
            client_id=req.client_id,
            venue=req.venue,
            symbol=req.symbol,
            side=req.side,
            requested_qty=req.qty,
            filled_qty=0.0,
            avg_price=0.0,
            fee=0.0,
            status=OrderStatus.UNKNOWN,
            ts=self._clock.now(),
            error=error,
        )

    def _request(self, venue: str, symbol: str, side: Side, qty: float, limit: float) -> OrderRequest:
        return OrderRequest(self.new_client_id(), venue, symbol, side, qty, limit)

    # ------------------------------------------------------------------ cross-venue arb

    async def execute(self, signal: Signal, size: float) -> ExecutionReport:
        """Run a CROSS_VENUE signal at ``size``: both legs at once, then hedge/unwind any excess."""
        started = self._clock.now()
        buy_leg, sell_leg = self._arb_legs(signal)
        bv, binst = self._instrument(buy_leg.venue, buy_leg.symbol)
        sv, sinst = self._instrument(sell_leg.venue, sell_leg.symbol)
        for venue in (bv.name, sv.name):
            self._client(venue)  # fail before sending anything, never between the legs
        report = ExecutionReport(signal.id, ExecutionOutcome.NO_FILL, started_ts=started)

        qty = _floor_qty(size, common_lot(binst.lot_size, sinst.lot_size))
        if qty <= 0:
            report.notes.append(f"size {size:g} is below a lot on both venues")
            return self._finish(report)
        ms = self._ex.max_slippage_bps
        buy_ref = self._ref_price(buy_leg)
        sell_ref = self._ref_price(sell_leg)
        buy_req = self._request(bv.name, signal.symbol, Side.BUY, qty, _limit(buy_ref, Side.BUY, ms, binst.tick_size))
        sell_req = self._request(
            sv.name, signal.symbol, Side.SELL, qty, _limit(sell_ref, Side.SELL, ms, sinst.tick_size)
        )
        buy_res, sell_res = await asyncio.gather(self.send(buy_req), self.send(sell_req))
        report.orders += [buy_res, sell_res]
        report.notes += [f"{r.client_id} on {r.venue} rejected: {r.error}"
                         for r in (buy_res, sell_res) if r.status is OrderStatus.REJECTED]

        unknown = [r for r in report.orders if r.status is OrderStatus.UNKNOWN]
        excess = _qty_sum((buy_res.filled_qty, -sell_res.filled_qty))
        dust = 1e-6 * min(binst.lot_size, sinst.lot_size)
        dust_left = 0.0
        if unknown:
            report.outcome = ExecutionOutcome.UNKNOWN
            report.notes.append("unknown order(s), not hedged: " + ", ".join(r.client_id for r in unknown))
        elif abs(excess) <= dust:
            filled = buy_res.filled_qty > 0 or sell_res.filled_qty > 0
            report.outcome = ExecutionOutcome.COMPLETED if filled else ExecutionOutcome.NO_FILL
        else:
            report.outcome, dust_left = await self._flatten(
                signal, report, excess, (buy_leg, buy_res), (sell_leg, sell_res), dust
            )
        return self._settle(report, signal.symbol, buy_leg, sell_leg, dust_left=dust_left)

    def _arb_legs(self, signal: Signal) -> tuple[Leg, Leg]:
        if signal.kind is not SignalKind.CROSS_VENUE:
            raise ValueError(f"execute() takes CROSS_VENUE signals, got {signal.kind}")
        buys = [g for g in signal.legs if g.side is Side.BUY]
        sells = [g for g in signal.legs if g.side is Side.SELL]
        if len(signal.legs) != 2 or len(buys) != 1 or len(sells) != 1:
            raise ValueError("a cross-venue signal needs exactly one BUY and one SELL leg")
        b, s = buys[0], sells[0]
        if not (b.symbol == s.symbol == signal.symbol) or b.venue == s.venue:
            raise ValueError("cross-venue legs must share the signal's symbol on two different venues")
        return b, s

    def _ref_price(self, leg: Leg) -> float:
        """Current book price for a taker on ``leg`` (ask/bid); the signal's quote if the book has none."""
        q = _usable(self._book.get(leg.venue, leg.symbol))
        return q.price_for(leg.side) if q is not None else leg.price

    async def _flatten(
        self,
        signal: Signal,
        report: ExecutionReport,
        excess: float,
        buy: tuple[Leg, OrderResult],
        sell: tuple[Leg, OrderResult],
        dust: float,
    ) -> tuple[ExecutionOutcome, float]:
        """Get rid of ``excess`` (+ long, - short): hedge on the other venue, then unwind on the origin.

        Returns the outcome and the unflattenable dust left (0.0 unless the
        outcome is FLATTENED with dust).
        """
        if excess > 0:  # bought more than sold: SELL the rest
            side, (origin_leg, origin), hedge_venue = Side.SELL, buy, sell[0].venue
        else:  # sold more than bought: BUY it back
            side, (origin_leg, origin), hedge_venue = Side.BUY, sell, buy[0].venue
        # The band is anchored on the over-filled leg's average fill price (its quote if a
        # venue reported a fill without a price, so a bad report can never widen the band).
        entry = origin.avg_price if origin.avg_price > 0 else origin_leg.price
        u = self._ex.unwind_slippage_bps
        remaining = abs(excess)

        attempts: list[tuple[str, str]] = []
        if self._ex.hedge_retry:
            attempts.append(("hedge", hedge_venue))
        attempts.append(("unwind", origin.venue))
        for what, venue in attempts:
            _, inst = self._instrument(venue, signal.symbol)
            qty = max(floor_to_step(remaining, inst.lot_size), 0.0)
            worst = _limit(entry, side, u, inst.tick_size)  # never beyond the unwind band
            if what == "hedge":
                q = _usable(self._book.get(venue, signal.symbol))
                limit = worst
                if q is not None:
                    at_market = _limit(q.price_for(side), side, self._ex.max_slippage_bps, inst.tick_size)
                    limit = min(at_market, worst) if side is Side.BUY else max(at_market, worst)
            else:
                limit = worst
            why = _unsendable(inst, venue, qty, limit)
            if why is not None:  # the venue would refuse it: do not send it
                report.notes.append(f"{what}: {remaining:g} is {why}")
                continue
            res = await self.send(self._request(venue, signal.symbol, side, qty, limit))
            report.orders.append(res)
            report.notes.append(f"{what} {side.value} {qty:g} on {venue} @<= {limit:g}: {res.status.value} "
                                f"{res.filled_qty:g}")
            if res.status is OrderStatus.UNKNOWN:
                report.notes.append(f"{what} order {res.client_id} is unknown: stopped")
                return ExecutionOutcome.UNKNOWN, 0.0
            remaining = _qty_sum((remaining, -res.filled_qty))
            if remaining <= dust:
                return ExecutionOutcome.FLATTENED, 0.0
        if self._unflattenable(signal.symbol, remaining, side, entry, (buy[0].venue, sell[0].venue)):
            report.notes.append(
                f"dust {excess / abs(excess) * remaining:+g} left: below the lot or the min notional on every venue, "
                "so no order can flatten it; it stays in the exposure figures"
            )
            log.warning("signal %s left %g %s of dust no order can flatten", report.signal_id, remaining,
                        signal.symbol)
            return ExecutionOutcome.FLATTENED, remaining
        return ExecutionOutcome.RESIDUAL, 0.0

    def _unflattenable(self, symbol: str, qty: float, side: Side, entry: float, venues: Iterable[str]) -> bool:
        """True when no venue would accept an order for ``qty`` even at the edge of the unwind band."""
        for venue in venues:
            _, inst = self._instrument(venue, symbol)
            lots = max(floor_to_step(qty, inst.lot_size), 0.0)
            band_edge = _limit(entry, side, self._ex.unwind_slippage_bps, inst.tick_size)
            if _unsendable(inst, venue, lots, band_edge) is None:
                return False
        return True

    def _settle(self, report: ExecutionReport, symbol: str, buy_leg: Leg, sell_leg: Leg, *,
                dust_left: float = 0.0) -> ExecutionReport:
        """Fill in quantities and PnL from every order in the report."""
        bought = _qty_sum(o.filled_qty for o in report.orders if o.side is Side.BUY)
        sold = _qty_sum(o.filled_qty for o in report.orders if o.side is Side.SELL)
        residual = _qty_sum((bought, -sold))
        dust = 1e-6 * min(self._instrument(g.venue, symbol)[1].lot_size for g in (buy_leg, sell_leg))
        if abs(residual) <= dust:
            residual = 0.0
        elif report.outcome in (ExecutionOutcome.COMPLETED, ExecutionOutcome.FLATTENED, ExecutionOutcome.NO_FILL):
            known_dust = (report.outcome is ExecutionOutcome.FLATTENED and dust_left > 0
                          and abs(abs(residual) - dust_left) <= dust)
            if not known_dust:
                # Safety net: never report flat when the fills say otherwise (e.g. a venue over-filled).
                report.notes.append(f"{report.outcome.value} but fills leave {residual:+g}: residual")
                report.outcome = ExecutionOutcome.RESIDUAL
        report.hedged_qty = min(bought, sold)
        report.residual_qty = residual
        report.fees = sum(o.fee for o in report.orders)
        cash = sum(o.notional * (-o.side.sign) for o in report.orders)  # sells - buys
        pnl = cash - report.fees
        if residual != 0.0:
            # The excess sits on the over-filled leg's venue: long on the buy venue, short on the sell venue.
            holder, other = (buy_leg, sell_leg) if residual > 0 else (sell_leg, buy_leg)
            mid = self._mark(symbol, holder.venue, other.venue, fallback=holder.price)
            pnl += residual * mid
            report.notes.append(f"residual {residual:+g} marked at mid {mid:g}")
            if report.outcome is ExecutionOutcome.RESIDUAL:
                log.error("signal %s left a residual of %+g %s", report.signal_id, residual, symbol)
        report.realized_pnl = pnl
        return self._finish(report)

    def _mark(self, symbol: str, *venues: str, fallback: float) -> float:
        for venue in venues:
            q = _usable(self._book.get(venue, symbol))
            if q is not None:
                return q.mid
        return fallback

    def _finish(self, report: ExecutionReport) -> ExecutionReport:
        report.finished_ts = self._clock.now()
        return report

    # ------------------------------------------------------------------ directional trades

    async def enter(self, signal: Signal, size: float) -> tuple[ExecutionReport, Position | None]:
        """One IOC entry for a REFERENCE_LAG signal; any fill opens a Position (stop/target/max_hold_s)."""
        started = self._clock.now()
        if signal.kind is not SignalKind.REFERENCE_LAG or len(signal.legs) != 1:
            raise ValueError("enter() takes a REFERENCE_LAG signal with exactly one leg")
        leg = signal.legs[0]
        _, inst = self._instrument(leg.venue, leg.symbol)
        self._client(leg.venue)
        report = ExecutionReport(signal.id, ExecutionOutcome.NO_FILL, started_ts=started)
        qty = _floor_qty(size, inst.lot_size)
        if qty <= 0:
            report.notes.append(f"size {size:g} is below the {leg.venue} lot")
            return self._finish(report), None

        limit = _limit(self._ref_price(leg), leg.side, self._ex.max_slippage_bps, inst.tick_size)
        res = await self.send(self._request(leg.venue, leg.symbol, leg.side, qty, limit))
        report.orders.append(res)
        report.fees = res.fee
        if res.status is OrderStatus.UNKNOWN:
            report.outcome = ExecutionOutcome.UNKNOWN
            report.notes.append(f"entry order {res.client_id} is unknown: no position recorded")
            return self._finish(report), None
        if res.filled_qty <= 0:
            return self._finish(report), None
        # What the account holds: a BUY whose commission was taken in base received less than it traded.
        held = _qty_sum((res.filled_qty, -res.base_fee)) if leg.side is Side.BUY else res.filled_qty
        if held != res.filled_qty:
            report.notes.append(f"commission of {res.base_fee:g} paid in base: the position holds {held:g}")

        max_hold = signal.max_hold_s if signal.max_hold_s is not None else self._cfg.reference_lag.max_hold_s
        position = Position(
            id=self._next_id("pos"),
            signal_id=signal.id,
            venue=leg.venue,
            symbol=leg.symbol,
            side=leg.side,
            qty=held,
            entry_price=res.avg_price,
            stop_price=signal.stop,
            target_price=signal.target,
            opened_ts=self._clock.now(),
            max_hold_s=max_hold,
            entry_fee=res.fee,
        )
        report.outcome = ExecutionOutcome.OPENED
        report.position_id = position.id
        if res.filled_qty < qty:
            report.notes.append(f"entry partially filled: {res.filled_qty:g} of {qty:g}")
        return self._finish(report), position

    async def exit_position(self, position: Position, reason: str, quote: Quote | None) -> ExecutionReport:
        """IOC for the open qty on the opposite side, crossing ``unwind_slippage_bps`` from ``quote``.

        Fully closed -> CLOSED, ``position.qty = 0``. Partially closed ->
        FLATTENED with a "partial exit" note and ``position.qty`` reduced;
        nothing filled -> NO_FILL. ``exit_attempts`` counts every attempt.
        ``realized_pnl`` covers the closed qty net of its share of the entry
        fee and the exit fee. ``residual_qty`` is the signed qty still open.

        Dust: when what is open (before or after this exit's fill) cannot be
        sent as an order, because it is below the lot or below the venue's
        ``min_notional`` at the exit limit, no order is sent for it: the report
        is CLOSED with a dust note and ``residual_qty`` = the dust, and the
        position keeps that qty (and its share of the entry fee) for the
        caller's accounting. A SELL limit is first raised toward the bid, if
        that is enough to clear the min notional.
        """
        started = self._clock.now()
        side = position.side.opposite()
        _, inst = self._instrument(position.venue, position.symbol)
        report = ExecutionReport(
            position.signal_id, ExecutionOutcome.NO_FILL, started_ts=started, position_id=position.id
        )
        position.exit_attempts += 1
        qty = _floor_qty(position.qty, inst.lot_size)
        ref = self._exit_ref(position, side, quote)
        limit = _limit(ref, side, self._ex.unwind_slippage_bps, inst.tick_size)
        if side is Side.SELL:
            limit = _fit_sell_notional(inst, qty, limit, ref)
        why = _unsendable(inst, position.venue, qty, limit)
        if why is not None:
            return self._close_as_dust(report, position, reason, why)
        res = await self.send(self._request(position.venue, position.symbol, side, qty, limit))
        report.orders.append(res)
        report.fees = res.fee
        if res.status is OrderStatus.UNKNOWN:
            report.outcome = ExecutionOutcome.UNKNOWN
            report.residual_qty = position.side.sign * position.qty
            report.notes.append(f"exit ({reason}) order {res.client_id} is unknown: position left as is")
            return self._finish(report)
        if res.filled_qty <= 0:
            report.residual_qty = position.side.sign * position.qty
            report.notes.append(f"exit ({reason}) not filled: {res.status.value}")
            return self._finish(report)

        closed = min(res.filled_qty, position.qty)
        entry_fee_share = position.entry_fee * closed / position.qty
        gross = position.side.sign * closed * (res.avg_price - position.entry_price)
        report.realized_pnl = gross - entry_fee_share - res.fee
        position.entry_fee -= entry_fee_share
        position.qty = _qty_sum((position.qty, -closed))
        if position.qty <= 1e-6 * inst.lot_size:
            position.qty = 0.0
            position.entry_fee = 0.0
            report.outcome = ExecutionOutcome.CLOSED
            report.notes.append(f"closed ({reason}) {closed:g} @ {res.avg_price:g}")
            return self._finish(report)
        rest = _floor_qty(position.qty, inst.lot_size)
        rest_limit = _fit_sell_notional(inst, rest, limit, ref) if side is Side.SELL else limit
        why = _unsendable(inst, position.venue, rest, rest_limit)
        if why is not None:
            report.notes.append(f"closed ({reason}) {closed:g} @ {res.avg_price:g}")
            return self._close_as_dust(report, position, reason, why)
        report.outcome = ExecutionOutcome.FLATTENED
        report.residual_qty = position.side.sign * position.qty
        report.notes.append(f"partial exit ({reason}): closed {closed:g}, {position.qty:g} still open")
        return self._finish(report)

    def _close_as_dust(self, report: ExecutionReport, position: Position, reason: str, why: str) -> ExecutionReport:
        """CLOSED: what is left of ``position`` cannot be sold by any order, so stop managing it."""
        report.outcome = ExecutionOutcome.CLOSED
        report.residual_qty = position.side.sign * position.qty
        report.notes.append(
            f"exit ({reason}): {position.qty:g} {position.symbol} left on {position.venue} is {why}; no order can "
            "close it, so the position is closed as dust (it stays in the account and in the exposure figures)"
        )
        log.warning("position %s closed with %g %s of dust left on %s (%s)", position.id, position.qty,
                    position.symbol, position.venue, why)
        return self._finish(report)

    def _exit_ref(self, position: Position, side: Side, quote: Quote | None) -> float:
        """Exit reference price: ``quote`` if it is this position's, else the book, else the entry price."""
        for q in (quote, self._book.get(position.venue, position.symbol)):
            q = _usable(q)
            if q is not None and q.venue == position.venue and q.symbol == position.symbol:
                return q.price_for(side)
        log.warning("no usable quote to exit %s; using the entry price as reference", position.id)
        return position.entry_price
