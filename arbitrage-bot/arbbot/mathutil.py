"""Exchange-grid rounding and basis-point helpers.

Rounding goes through Decimal on the string form of the float so that values
like 0.3 / 0.1 land exactly on the grid instead of one step below it.
"""

from __future__ import annotations

import math
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from .models import Side


def _grid(x: float, step: float, rounding: str) -> float:
    if step <= 0:
        return x
    d, s = Decimal(repr(x)), Decimal(repr(step))
    return float((d / s).to_integral_value(rounding=rounding) * s)


def floor_to_step(x: float, step: float) -> float:
    """Largest grid value <= x (lot sizes: never send more than intended)."""
    return _grid(x, step, ROUND_FLOOR)


def ceil_to_step(x: float, step: float) -> float:
    return _grid(x, step, ROUND_CEILING)


def common_lot(*lots: float) -> float:
    """Smallest step that is a whole multiple of every lot (exact, via Decimal).

    Flooring to it lands on every venue's lot grid at once: 0.001 and 0.01 ->
    0.01; 0.002 and 0.003 -> 0.006. Non-positive lots are ignored; 0.0 if none remain.
    """
    ds = [Decimal(repr(x)) for x in lots if x > 0]
    if not ds:
        return 0.0
    exp = max(max(-int(d.as_tuple().exponent) for d in ds), 0)
    scale = Decimal(10) ** exp
    return float(Decimal(math.lcm(*(int(d * scale) for d in ds))) / scale)


def quantize_limit(price: float, tick: float, side: Side) -> float:
    """Round a limit price to the tick grid without exceeding the intended allowance.

    BUY limits round down and SELL limits round up, so the order is never more
    aggressive than requested. Because quoted prices already sit on the grid,
    ``quantize_limit(ask * (1 + s), tick, BUY) >= ask`` for any s >= 0.
    """
    return floor_to_step(price, tick) if side is Side.BUY else ceil_to_step(price, tick)


def bps(x: float) -> float:
    """Fraction -> basis points."""
    return x * 1e4


def from_bps(b: float) -> float:
    """Basis points -> fraction."""
    return b / 1e4


def edge_bps(buy_price: float, sell_price: float) -> float:
    """Gross edge of buying at ``buy_price`` and selling at ``sell_price``, in bps of the buy."""
    return (sell_price - buy_price) / buy_price * 1e4
