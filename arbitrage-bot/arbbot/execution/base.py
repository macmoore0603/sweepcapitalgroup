"""Order-routing contract implemented by PaperExchange and live venue clients."""

from __future__ import annotations

from typing import Protocol

from ..models import OrderRequest, OrderResult


class ExchangeError(Exception):
    """Transport-level failure: the order's fate is unknown until reconciled."""


class ExchangeClient(Protocol):
    venue: str

    async def place_ioc(self, req: OrderRequest) -> OrderResult:
        """Send an immediate-or-cancel limit order and return its final state.

        Venue rejections (insufficient balance, filters, rate limits) are
        returned as ``OrderStatus.REJECTED``, not raised. Transport failures
        (timeouts, dropped connections) raise ``ExchangeError`` because the
        order may or may not have reached the matching engine.
        """
        ...

    async def query_order(self, req: OrderRequest) -> OrderResult | None:
        """Look up an order by ``req.client_id``.

        Returns None only when the venue says the order does not exist. Raises
        ``ExchangeError`` when the state cannot be determined (transport failure
        or any other venue error); the engine then reports the order UNKNOWN.
        """
        ...
