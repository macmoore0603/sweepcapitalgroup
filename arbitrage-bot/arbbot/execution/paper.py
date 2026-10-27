"""Simulated venue: fills IOC limit orders against the book as of order ARRIVAL.

An order sent at ``t`` reaches the venue at ``t + latency``; a paper fill is
priced from the quote that was standing then, never from the quote that fired
the signal. ``book_at(symbol, t)`` answers "what was this venue's top of book
at time t" (``QuoteHistory.as_of`` in backtests, the live ``QuoteBook`` in
paper trading).

Waiting for arrival goes through ``sleep_until`` so the same code runs live
(a real sleep, ``realtime_sleep_until``) and in a backtest
(``simclock_sleep_until``: ``SimClock.set(max(now, arrival))``). Two legs sent
together both read the same send time before either advances the clock, so
each leg sees the book as of its OWN arrival time.

Liquidity is consumed: an order takes what it fills from the quote it fills
against, and later orders against that SAME quote (another signal, or the
hedge of a leg that ran out of displayed size) only see what is left. A newer
quote for the venue/symbol replaces the level and resets it. Without this a
backtest could buy one displayed 1.0 BTC ask several times over.

Venue filters are enforced like the real venue: an order whose notional
``qty * limit_price`` is below the instrument's ``min_notional`` is REJECTED
("Filter failure: NOTIONAL"), and, when a ``portfolio`` is given, an order
the venue's balance cannot cover (SELL: base, BUY: ``qty * limit`` quote) is
REJECTED ("insufficient balance"), as Binance answers -2010.

The paper venue never changes the Portfolio (it only reads balances): the
engine applies every fill.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from decimal import Decimal

from ..clock import Clock, SimClock
from ..config import InstrumentConfig, VenueConfig
from ..mathutil import floor_to_step
from ..models import OrderRequest, OrderResult, OrderStatus, Quote, Side, split_symbol
from ..portfolio import Portfolio

BookAt = Callable[[str, float], Quote | None]
SleepUntil = Callable[[float], Awaitable[None]]


def realtime_sleep_until(clock: Clock) -> SleepUntil:
    """Live paper trading: really wait until ``clock.now() >= t``."""

    async def sleep_until(t: float) -> None:
        await asyncio.sleep(max(t - clock.now(), 0.0))

    return sleep_until


def simclock_sleep_until(clock: SimClock) -> SleepUntil:
    """Backtest: jump the simulated clock to ``max(now, t)`` (it never goes backwards)."""

    async def sleep_until(t: float) -> None:
        clock.set(max(clock.now(), t))

    return sleep_until


def _mul(a: float, b: float) -> float:
    """``a * b`` on the decimal forms, so 0.7 * 0.1 is 0.07 and not one lot below it after flooring."""
    return float(Decimal(repr(a)) * Decimal(repr(b)))


def _add(a: float, b: float) -> float:
    """``a + b`` on the decimal forms (lot-grid quantities stay on the grid)."""
    return float(Decimal(repr(a)) + Decimal(repr(b)))


_BALANCE_TOL = 1e-9  # relative: float noise in the portfolio must not reject an order for exactly the balance


class PaperExchange:
    """``ExchangeClient`` for one venue, filling against ``book_at`` with latency, slippage and fees.

    BUY fills iff ``ask <= limit``, at ``min(qty, ask_size * fill_ratio - already
    taken from this quote)`` floored to the lot, price ``min(ask * (1 +
    slippage_bps/1e4), limit)``; SELL mirrored on the bid. The rest expires
    (IOC). Fee = ``filled * price * taker_fee_bps / 1e4``. A missing or invalid
    quote expires the order. Malformed requests (wrong venue, unknown symbol,
    non-positive qty/limit, reused client id), orders below ``min_notional``
    and (with a ``portfolio``) orders the balance cannot cover are REJECTED.
    """

    def __init__(
        self,
        venue: VenueConfig,
        book_at: BookAt,
        clock: Clock,
        *,
        sleep_until: SleepUntil,
        fill_ratio: float = 1.0,
        portfolio: Portfolio | None = None,
    ) -> None:
        if not 0.0 <= fill_ratio <= 1.0:
            raise ValueError(f"fill_ratio must be in [0, 1], got {fill_ratio}")
        self.venue = venue.name
        self.config = venue
        self._book_at = book_at
        self._clock = clock
        self._sleep_until = sleep_until
        self._fill_ratio = fill_ratio
        self._portfolio = portfolio
        self._orders: dict[str, OrderResult] = {}
        # (symbol, side) -> (the quote last filled against, base qty taken from it so far)
        self._taken: dict[tuple[str, Side], tuple[Quote, float]] = {}

    async def place_ioc(self, req: OrderRequest) -> OrderResult:
        sent = self._clock.now()
        await asyncio.sleep(0)  # let concurrently sent legs read the same send time
        arrival = sent + self.config.latency_ms / 1000.0
        await self._sleep_until(arrival)

        inst = self.config.instrument(req.symbol)
        problem = self._validate(req, inst)
        if problem is not None:
            return self._result(req, 0.0, 0.0, OrderStatus.REJECTED, arrival, error=problem, store=False)
        assert inst is not None
        if _mul(req.qty, req.limit_price) < inst.min_notional:
            return self._result(req, 0.0, 0.0, OrderStatus.REJECTED, arrival, store=False,
                                error=f"Filter failure: NOTIONAL (qty * limit < min_notional {inst.min_notional:g})")
        short = self._balance_problem(req)
        if short is not None:
            return self._result(req, 0.0, 0.0, OrderStatus.REJECTED, arrival, error=short, store=False)

        q = self._book_at(req.symbol, arrival)  # the book as of ARRIVAL, never as of the signal
        if q is None or not q.is_valid():
            return self._result(req, 0.0, 0.0, OrderStatus.EXPIRED, arrival, error="no quote")

        slip = self.config.slippage_bps / 1e4
        if req.side is Side.BUY:
            crosses = q.ask <= req.limit_price
            price = min(q.ask * (1 + slip), req.limit_price)
        else:
            crosses = q.bid >= req.limit_price
            price = max(q.bid * (1 - slip), req.limit_price)
        if not crosses:
            return self._result(req, 0.0, 0.0, OrderStatus.EXPIRED, arrival)

        key = (req.symbol, req.side)
        prev = self._taken.get(key)
        taken = prev[1] if prev is not None and prev[0] == q else 0.0
        available = _add(_mul(q.size_for(req.side), self._fill_ratio), -taken)
        filled = max(floor_to_step(min(req.qty, available), inst.lot_size), 0.0)
        if filled <= 0:
            return self._result(req, 0.0, 0.0, OrderStatus.EXPIRED, arrival)
        self._taken[key] = (q, _add(taken, filled))
        status = OrderStatus.FILLED if filled >= req.qty else OrderStatus.PARTIALLY_FILLED
        return self._result(req, filled, price, status, arrival)

    async def query_order(self, req: OrderRequest) -> OrderResult | None:
        return self._orders.get(req.client_id)

    def _balance_problem(self, req: OrderRequest) -> str | None:
        """Why the venue would refuse ``req`` for lack of balance (None if covered or no portfolio)."""
        if self._portfolio is None:
            return None
        base, quote = split_symbol(req.symbol)
        if req.side is Side.SELL:
            asset, need = base, req.qty
        else:
            asset, need = quote, _mul(req.qty, req.limit_price)
        have = self._portfolio.balance(self.venue, asset)
        if need > have + _BALANCE_TOL * max(abs(have), need, 1.0):
            return f"insufficient balance: needs {need:g} {asset}, {self.venue} holds {have:g}"
        return None

    def _validate(self, req: OrderRequest, inst: InstrumentConfig | None) -> str | None:
        if req.venue != self.venue:
            return f"order for venue {req.venue!r} sent to {self.venue!r}"
        if inst is None:
            return f"unknown symbol {req.symbol!r}"
        if not req.qty > 0 or not req.limit_price > 0:
            return "qty and limit_price must be > 0"
        if req.tif != "IOC":
            return f"unsupported tif {req.tif!r}"
        if req.client_id in self._orders:
            return f"duplicate client_id {req.client_id!r}"
        return None

    def _result(
        self,
        req: OrderRequest,
        filled: float,
        price: float,
        status: OrderStatus,
        ts: float,
        *,
        error: str | None = None,
        store: bool = True,
    ) -> OrderResult:
        fee = filled * price * self.config.taker_fee_bps / 1e4 if filled > 0 else 0.0
        res = OrderResult(
            client_id=req.client_id,
            venue=self.venue,
            symbol=req.symbol,
            side=req.side,
            requested_qty=req.qty,
            filled_qty=filled,
            avg_price=price if filled > 0 else 0.0,
            fee=fee,
            status=status,
            ts=ts,
            error=error,
        )
        if store:
            self._orders[req.client_id] = res
        return res
