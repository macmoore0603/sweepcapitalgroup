"""Core value types shared by every module.

Units, everywhere:
  * price    -- quote currency per 1 unit of base (BTC-USDT: USDT per BTC)
  * size/qty -- base units (BTC)
  * money    -- fees, PnL and notional are in the quote currency
  * time     -- float seconds since the epoch, always read from the injected
                Clock so backtests are deterministic

Symbols are canonical ``BASE-QUOTE`` strings (``BTC-USDT``). Each venue's own
spelling lives in config (``InstrumentConfig.venue_symbol``). Two quotes are
only comparable when their canonical symbols are identical: BTC-USD and
BTC-USDT are different instruments with a floating basis between them.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import StrEnum


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"

    @property
    def sign(self) -> int:
        """+1 for BUY, -1 for SELL (change in base position)."""
        return 1 if self is Side.BUY else -1

    def opposite(self) -> Side:
        return Side.SELL if self is Side.BUY else Side.BUY


def split_symbol(symbol: str) -> tuple[str, str]:
    """``"BTC-USDT"`` -> ``("BTC", "USDT")``."""
    base, sep, quote = symbol.partition("-")
    if not sep or not base or not quote or "-" in quote:
        raise ValueError(f"symbol must be BASE-QUOTE, got {symbol!r}")
    return base, quote


@dataclass(frozen=True, slots=True)
class Quote:
    """Top of book for one instrument on one venue."""

    venue: str
    symbol: str
    bid: float
    bid_size: float
    ask: float
    ask_size: float
    ts_local: float  # when we received it (Clock time); staleness is measured on this
    ts_exchange: float | None = None  # venue event time, if the venue sends one
    seq: int | None = None  # venue update id, if any; used to drop out-of-order updates

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_bps(self) -> float:
        return (self.ask - self.bid) / self.mid * 1e4

    def is_valid(self) -> bool:
        """Positive prices and sizes, and not crossed (a crossed book is a data glitch)."""
        return (
            self.bid > 0
            and self.ask > 0
            and self.bid_size > 0
            and self.ask_size > 0
            and self.ask >= self.bid
        )

    def price_for(self, side: Side) -> float:
        """Price a taker pays (BUY -> ask) or receives (SELL -> bid)."""
        return self.ask if side is Side.BUY else self.bid

    def size_for(self, side: Side) -> float:
        """Displayed size available to a taker on ``side``."""
        return self.ask_size if side is Side.BUY else self.bid_size

    def depth_notional(self) -> float:
        """Thinner side of the top of book, in quote currency."""
        return min(self.bid * self.bid_size, self.ask * self.ask_size)

    def age(self, now: float) -> float:
        return now - self.ts_local


@dataclass(frozen=True, slots=True)
class FeedStatus:
    """Connection state change emitted by a feed (quotes from a dead feed are stale)."""

    venue: str
    connected: bool
    ts_local: float
    reason: str = ""


FeedEvent = Quote | FeedStatus


class SignalKind(StrEnum):
    CROSS_VENUE = "cross_venue"  # same instrument, buy on one venue, sell on another
    REFERENCE_LAG = "reference_lag"  # one venue lags a reference venue: single directional trade


@dataclass(frozen=True, slots=True)
class Leg:
    venue: str
    symbol: str
    side: Side
    price: float  # quoted price the edge was computed from (ask for BUY, bid for SELL)
    size: float  # displayed size at that price when the signal fired


@dataclass(frozen=True, slots=True)
class Signal:
    """A cleared trade idea: ``{market, spread, size, entry, stop, target}`` plus provenance.

    CROSS_VENUE: legs = (buy leg, sell leg). entry = buy price, target = sell
      price (locked in if both legs fill), stop = worst price an unhedged
      residual may be flattened at.
    REFERENCE_LAG: legs = (single leg,). entry = quoted entry price, target =
      expected convergence price, stop = hard stop price; the position is
      closed by the PositionMonitor at stop, target or ``max_hold_s``.
    """

    id: str
    kind: SignalKind
    symbol: str
    market: str  # human label, e.g. "BTC-USDT buy@binance sell@bybit"
    legs: tuple[Leg, ...]
    size: float  # proposed base size before risk sizing
    gross_edge_bps: float  # raw spread before costs
    cost_bps: float  # fees on all legs + expected slippage + buffer
    net_edge_bps: float  # gross - cost; only emitted when >= the configured threshold
    expected_pnl: float  # quote currency, at ``size``, net of fees and expected slippage
    entry: float
    stop: float
    target: float
    ts: float
    max_hold_s: float | None = None  # REFERENCE_LAG only

    @property
    def spread_bps(self) -> float:
        return self.gross_edge_bps


class OrderStatus(StrEnum):
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"  # IOC: filled some, rest expired
    EXPIRED = "expired"  # IOC: nothing filled
    REJECTED = "rejected"  # venue refused it (balance, filters, rate limit)
    UNKNOWN = "unknown"  # transport failure and the order could not be reconciled


@dataclass(frozen=True, slots=True)
class OrderRequest:
    client_id: str
    venue: str
    symbol: str  # canonical
    side: Side
    qty: float  # base units, already rounded to the venue lot size
    limit_price: float  # worst acceptable price, already rounded to the venue tick
    tif: str = "IOC"


@dataclass(frozen=True, slots=True)
class OrderResult:
    client_id: str
    venue: str
    symbol: str
    side: Side
    requested_qty: float
    filled_qty: float
    avg_price: float  # 0.0 when nothing filled
    fee: float  # quote currency
    status: OrderStatus
    ts: float
    error: str | None = None

    @property
    def remaining_qty(self) -> float:
        return max(self.requested_qty - self.filled_qty, 0.0)

    @property
    def notional(self) -> float:
        return self.filled_qty * self.avg_price


class ExecutionOutcome(StrEnum):
    COMPLETED = "completed"  # all legs filled the same qty (hedged), possibly < requested
    NO_FILL = "no_fill"  # nothing filled anywhere
    FLATTENED = "flattened"  # legs filled unequally; the excess was hedged or unwound to flat
    RESIDUAL = "residual"  # could not get flat: kill switch, manual intervention
    UNKNOWN = "unknown"  # an order's state is unknown: kill switch, reconcile manually
    OPENED = "opened"  # REFERENCE_LAG entry filled; a Position is now open
    CLOSED = "closed"  # a REFERENCE_LAG position was closed (stop/target/time)


@dataclass(slots=True)
class ExecutionReport:
    signal_id: str
    outcome: ExecutionOutcome
    orders: list[OrderResult] = field(default_factory=list)
    hedged_qty: float = 0.0  # base qty that ended fully hedged (cross-venue)
    residual_qty: float = 0.0  # signed base qty left unhedged (+ long, - short)
    realized_pnl: float = 0.0  # quote ccy, net of fees; residual marked to mid
    fees: float = 0.0
    started_ts: float = 0.0
    finished_ts: float = 0.0
    position_id: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Position:
    """An open directional position (REFERENCE_LAG trades)."""

    id: str
    signal_id: str
    venue: str
    symbol: str
    side: Side  # side of the entry
    qty: float  # remaining open base qty (> 0)
    entry_price: float
    stop_price: float
    target_price: float
    opened_ts: float
    max_hold_s: float
    entry_fee: float = 0.0
    exit_attempts: int = 0


_ids = itertools.count(1)


def next_id(prefix: str) -> str:
    """Process-unique, deterministic ids (no randomness, so backtests replay identically)."""
    return f"{prefix}-{next(_ids)}"
