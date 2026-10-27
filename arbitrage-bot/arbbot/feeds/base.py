"""Market-data contracts: the Feed protocol and the QuoteBook every module reads."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Protocol

from ..models import FeedEvent, Quote


class Feed(Protocol):
    """A venue's market data as an async stream of Quote / FeedStatus events.

    Implementations reconnect on their own and must emit
    ``FeedStatus(connected=False)`` whenever the stream drops, so consumers can
    invalidate that venue's quotes instead of trading on a frozen book.
    """

    venue: str

    def stream(self) -> AsyncIterator[FeedEvent]: ...


class BookView(Protocol):
    """Read access to the latest quote per (venue, symbol): what the execution engine prices from."""

    def get(self, venue: str, symbol: str) -> Quote | None: ...


def _same_level(a: Quote, b: Quote) -> bool:
    return (a.bid, a.bid_size, a.ask, a.ask_size) == (b.bid, b.bid_size, b.ask, b.ask_size)


class QuoteBook:
    """Latest valid top of book per (venue, symbol).

    Invalid (crossed / non-positive) quotes are dropped. When quotes carry a
    ``seq``, an update with a lower seq is dropped as out of order, and so is
    one with the same seq but different prices or sizes. The same seq with
    the same prices and sizes is a venue re-confirming an unchanged book
    (Bybit re-sends its level-1 snapshot every 3 s with the same ``u``): it
    is stored, so the quote's ``ts_local`` (staleness) is refreshed.
    """

    def __init__(self) -> None:
        self._by_symbol: dict[str, dict[str, Quote]] = {}

    def update(self, quote: Quote) -> bool:
        """Store ``quote``. Returns False if it was rejected (invalid or out of order)."""
        if not quote.is_valid():
            return False
        venues = self._by_symbol.setdefault(quote.symbol, {})
        prev = venues.get(quote.venue)
        if prev is not None and prev.seq is not None and quote.seq is not None:
            if quote.seq < prev.seq:
                return False
            if quote.seq == prev.seq and not (_same_level(quote, prev) and quote.ts_local >= prev.ts_local):
                return False
        venues[quote.venue] = quote
        return True

    def get(self, venue: str, symbol: str) -> Quote | None:
        return self._by_symbol.get(symbol, {}).get(venue)

    def quotes_for(self, symbol: str) -> Mapping[str, Quote]:
        """venue -> latest quote for ``symbol`` (read-only view)."""
        return self._by_symbol.get(symbol, {})

    def fresh(self, venue: str, symbol: str, now: float, max_age_s: float) -> Quote | None:
        q = self.get(venue, symbol)
        return q if q is not None and q.age(now) <= max_age_s else None

    def invalidate_venue(self, venue: str) -> None:
        """Forget every quote from ``venue`` (call on disconnect)."""
        for venues in self._by_symbol.values():
            venues.pop(venue, None)

    def symbols(self) -> tuple[str, ...]:
        return tuple(self._by_symbol)
