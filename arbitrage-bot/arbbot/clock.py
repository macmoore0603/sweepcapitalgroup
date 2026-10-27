"""Injectable time source: wall clock live, simulated clock in backtests."""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float: ...


class WallClock:
    def now(self) -> float:
        return time.time()


class SimClock:
    """Backtest clock. Time only moves forward; the replay loop advances it per event."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def now(self) -> float:
        return self._t

    def set(self, t: float) -> None:
        if t < self._t:
            raise ValueError(f"SimClock cannot go backwards ({t} < {self._t})")
        self._t = t

    def advance(self, dt: float) -> None:
        self.set(self._t + dt)
