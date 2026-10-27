"""Per-venue balances and the net exposure they imply.

Cross-venue spot arbitrage never transfers coins mid-trade: it needs quote
currency pre-funded on the buy venue and base pre-funded on the sell venue,
and each completed arb shifts inventory between them. This class is the single
source of truth for those balances in paper/backtest mode (live mode should
reconcile it against the venues' own balance endpoints).

Fees are charged in quote currency (deducted from the quote balance). A venue
that takes part of the commission in the base asset reports it as
``OrderResult.base_fee``; ``apply_base_fee`` moves that part from the quote
balance to the base balance, so the base balance matches what the account
really received. The quote equivalent is what matters for PnL.

Reservations: inventory that backs an open directional position is not free
for new trades. ``set_reservations`` installs a source of
``{venue: {asset: qty}}`` (the bot derives it from its open positions);
``sellable`` and ``buying_power`` subtract it, balances do not.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping

from .models import Side, split_symbol

Reservations = Callable[[], Mapping[str, Mapping[str, float]]]


class Portfolio:
    def __init__(self, balances: Mapping[str, Mapping[str, float]] | None = None) -> None:
        self._bal: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for venue, assets in (balances or {}).items():
            for asset, qty in assets.items():
                self._bal[venue][asset] = float(qty)
        self._initial = self.snapshot()
        self._reservations: Reservations | None = None

    def balance(self, venue: str, asset: str) -> float:
        return self._bal[venue][asset]

    def total(self, asset: str) -> float:
        return sum(assets.get(asset, 0.0) for assets in self._bal.values())

    def initial_total(self, asset: str) -> float:
        return sum(assets.get(asset, 0.0) for assets in self._initial.values())

    def apply_fill(self, venue: str, symbol: str, side: Side, qty: float, price: float, fee: float) -> None:
        if qty <= 0:
            return
        base, quote = split_symbol(symbol)
        b = self._bal[venue]
        b[base] += side.sign * qty
        b[quote] -= side.sign * qty * price + fee

    def apply_base_fee(self, venue: str, symbol: str, base_fee: float, price: float) -> None:
        """Move the part of a fill's fee paid in base from the quote balance to the base balance.

        ``apply_fill`` charged the whole fee (``base_fee`` valued at ``price``
        included) to the quote balance; the venue actually took ``base_fee`` base.
        """
        if base_fee <= 0:
            return
        base, quote = split_symbol(symbol)
        b = self._bal[venue]
        b[base] -= base_fee
        b[quote] += base_fee * price

    def set_reservations(self, source: Reservations | None) -> None:
        """Install (or clear) the source of inventory reserved for open positions."""
        self._reservations = source

    def reserved(self, venue: str, asset: str) -> float:
        if self._reservations is None:
            return 0.0
        return max(float(self._reservations().get(venue, {}).get(asset, 0.0)), 0.0)

    def net_base_change(self, asset: str) -> float:
        """Base units gained (+) or lost (-) across all venues since start: the directional exposure."""
        return self.total(asset) - self.initial_total(asset)

    def buying_power(self, venue: str, symbol: str, price: float, fee_bps: float) -> float:
        """Max base qty this venue's unreserved quote balance can buy at ``price`` including the taker fee."""
        _, quote = split_symbol(symbol)
        cash = self._bal[venue][quote] - self.reserved(venue, quote)
        unit_cost = price * (1 + fee_bps / 1e4)
        return max(cash / unit_cost, 0.0) if unit_cost > 0 else 0.0

    def sellable(self, venue: str, symbol: str) -> float:
        """Base this venue holds that is not reserved for an open position."""
        base, _ = split_symbol(symbol)
        return max(self._bal[venue][base] - self.reserved(venue, base), 0.0)

    def snapshot(self) -> dict[str, dict[str, float]]:
        return {v: dict(a) for v, a in self._bal.items()}

    def equity(self, prices: Mapping[str, float], quote_asset: str) -> float:
        """Total value in ``quote_asset``; ``prices`` maps other assets to their price in it."""
        total = 0.0
        for assets in self._bal.values():
            for asset, qty in assets.items():
                total += qty if asset == quote_asset else qty * prices.get(asset, 0.0)
        return total
