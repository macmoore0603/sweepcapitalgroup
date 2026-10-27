"""Tests for arbbot.signal: cross-venue and reference-lag mispricing logic.

Expected numbers are worked out by hand in each test (fees, slippage, sizes,
EMA weights), never by calling the code under test.
"""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from arbbot.clock import SimClock
from arbbot.config import (
    BotConfig,
    ExecutionConfig,
    InstrumentConfig,
    ReferenceLagConfig,
    RiskConfig,
    SignalConfig,
    VenueConfig,
    validate,
)
from arbbot.feeds.base import QuoteBook
from arbbot.models import Quote, Side, SignalKind
from arbbot.portfolio import Portfolio
from arbbot.signal import CrossVenueScanner, EdgeHistogram, ReferenceLagScanner, common_lot

SYM = "BTC-USDT"


# --------------------------------------------------------------------------- fixtures


def venue(
    name: str,
    *,
    fee: float = 10.0,
    slip: float = 1.0,
    symbols: tuple[str, ...] = (SYM,),
    lot: float = 0.001,
    min_notional: float = 5.0,
) -> VenueConfig:
    return VenueConfig(
        name=name,
        feed="binance",
        taker_fee_bps=fee,
        slippage_bps=slip,
        instruments=tuple(
            InstrumentConfig(symbol=s, venue_symbol=s.replace("-", ""), tick_size=0.01, lot_size=lot,
                             min_notional=min_notional)
            for s in symbols
        ),
    )


def make_cfg(*venues: VenueConfig, **signal_kw: float) -> BotConfig:
    """X = 5 bps, participation 0.5, no persistence, 1 s cooldown, max_slippage 5, unwind 50."""
    sig = SignalConfig(min_net_edge_bps=5.0, participation=0.5, persistence_ms=0.0, cooldown_ms=1000.0)
    cfg = BotConfig(
        venues=venues,
        signal=replace(sig, **signal_kw),
        risk=RiskConfig(max_order_notional=500.0, max_net_exposure_notional=1000.0, max_quote_age_ms=1500.0),
        execution=ExecutionConfig(max_slippage_bps=5.0, unwind_slippage_bps=50.0),
    )
    validate(cfg)
    return cfg


def q(venue_name: str, bid: float, ask: float, ts: float, *, bid_size: float = 3.0, ask_size: float = 2.0,
      symbol: str = SYM, seq: int | None = None) -> Quote:
    return Quote(venue=venue_name, symbol=symbol, bid=bid, bid_size=bid_size, ask=ask, ask_size=ask_size,
                 ts_local=ts, seq=seq)


def rich(*venues: str, usdt: float = 1_000_000.0, btc: float = 100.0) -> Portfolio:
    return Portfolio({v: {"USDT": usdt, "BTC": btc} for v in venues})


def feed(scanner, book: QuoteBook, pf: Portfolio, quote: Quote):
    book.update(quote)
    return scanner.on_quote(quote, book, pf)


# --------------------------------------------------------------------------- cross venue: math


def test_25bps_gross_with_22bps_costs_does_not_fire():
    # costs: 10 + 10 bps taker + 1 + 1 bps slippage = 22 bps; X = 5.
    # gross 25 bps -> net 3 < 5 -> no signal.
    clock = SimClock(0.0)
    cfg = make_cfg(venue("A"), venue("B"))
    scanner = CrossVenueScanner(cfg, clock)
    pf = rich("A", "B")
    buy, sell = q("A", 99.99, 100.00, 0.0), q("B", 100.25, 100.26, 0.0)
    assert scanner.evaluate_pair(buy, sell, pf) is None

    book = QuoteBook()
    book.update(buy)
    assert feed(scanner, book, pf, sell) == []
    assert scanner.stats.rejects["below_threshold"] == 2  # A->B (net 3) and B->A (negative)
    assert scanner.stats.candidates == 0
    assert scanner.stats.best_net_bps == pytest.approx(3.0)


def test_30bps_gross_fires_with_net_8_and_exact_signal_fields():
    clock = SimClock(10.0)
    cfg = make_cfg(venue("A"), venue("B"))
    scanner = CrossVenueScanner(cfg, clock)
    pf = rich("A", "B")
    buy = q("A", 99.99, 100.00, 10.0, ask_size=2.0)
    sell = q("B", 100.30, 100.31, 10.0, bid_size=3.0)

    sig = scanner.evaluate_pair(buy, sell, pf)
    assert sig is not None
    assert sig.kind is SignalKind.CROSS_VENUE
    assert sig.symbol == SYM
    assert sig.market == "BTC-USDT buy@A sell@B"
    assert sig.gross_edge_bps == pytest.approx(30.0)
    assert sig.cost_bps == pytest.approx(22.0)
    assert sig.net_edge_bps == pytest.approx(8.0)
    # size = 0.5 * min(2.0, 3.0) = 1.0 (500 / 100 = 5 cap, ample inventory, lot 0.001)
    assert sig.size == pytest.approx(1.0)
    # pnl = 1.0 * (100.30 * (1 - 11bps) - 100.00 * (1 + 11bps)) = (100.30 - 0.11033) - 100.11
    assert sig.expected_pnl == pytest.approx(0.07967, abs=1e-9)
    assert sig.entry == 100.00
    assert sig.target == 100.30
    assert sig.stop == pytest.approx(99.50)  # 100 * (1 - 50bps)
    assert sig.ts == 10.0
    assert sig.max_hold_s is None
    b_leg, s_leg = sig.legs
    assert (b_leg.venue, b_leg.side, b_leg.price, b_leg.size) == ("A", Side.BUY, 100.00, 2.0)
    assert (s_leg.venue, s_leg.side, s_leg.price, s_leg.size) == ("B", Side.SELL, 100.30, 3.0)


def test_net_edge_exactly_at_threshold_fires_and_just_below_does_not():
    # 10000 -> 10027 is exactly 27.0 bps gross in floating point: net = 27 - 22 = 5 = X.
    clock = SimClock(0.0)
    cfg = make_cfg(venue("A"), venue("B"))
    scanner = CrossVenueScanner(cfg, clock)
    pf = rich("A", "B")
    sig = scanner.evaluate_pair(q("A", 9999.0, 10000.0, 0.0), q("B", 10027.0, 10028.0, 0.0), pf)
    assert sig is not None and sig.net_edge_bps == 5.0
    assert scanner.evaluate_pair(q("A", 9999.0, 10000.0, 0.0), q("B", 10026.9, 10028.0, 0.0), pf) is None


def test_costs_use_each_venues_own_fee_and_slippage():
    # buy on A (fee 4, slip 1), sell on B (fee 20, slip 3): cost = 28 bps; gross 40 -> net 12.
    clock = SimClock(0.0)
    cfg = make_cfg(venue("A", fee=4.0, slip=1.0), venue("B", fee=20.0, slip=3.0))
    scanner = CrossVenueScanner(cfg, clock)
    sig = scanner.evaluate_pair(q("A", 99.99, 100.00, 0.0), q("B", 100.40, 100.41, 0.0), rich("A", "B"))
    assert sig is not None
    assert sig.cost_bps == pytest.approx(28.0)
    assert sig.net_edge_bps == pytest.approx(12.0)
    # pnl = 1.0 * (100.40 * (1 - 23bps) - 100.00 * (1 + 5bps)) = 100.169080 - 100.05
    assert sig.expected_pnl == pytest.approx(0.11908, abs=1e-9)


# --------------------------------------------------------------------------- cross venue: symbols, staleness, validity


def test_btc_usd_is_never_paired_with_btc_usdt():
    clock = SimClock(0.0)
    cfg = make_cfg(venue("A", symbols=("BTC-USD", "BTC-USDT")), venue("B", symbols=("BTC-USD", "BTC-USDT")))
    scanner = CrossVenueScanner(cfg, clock)
    pf = Portfolio({v: {"USD": 1e6, "USDT": 1e6, "BTC": 100.0} for v in ("A", "B")})
    cheap_usd = q("A", 99.99, 100.00, 0.0, symbol="BTC-USD")
    rich_usdt = q("B", 110.00, 110.01, 0.0, symbol="BTC-USDT")  # 1000 bps "edge" across symbols

    assert scanner.evaluate_pair(cheap_usd, rich_usdt, pf) is None
    book = QuoteBook()
    book.update(rich_usdt)
    assert feed(scanner, book, pf, cheap_usd) == []
    assert feed(scanner, book, pf, rich_usdt) == []
    assert scanner.stats.evaluations == 0
    assert scanner.stats.emitted == 0

    # the same-symbol counterpart does pair (and only within BTC-USD)
    sig = feed(scanner, book, pf, q("B", 100.30, 100.31, 0.0, symbol="BTC-USD"))
    assert len(sig) == 1 and sig[0].symbol == "BTC-USD" and sig[0].market == "BTC-USD buy@A sell@B"


def test_symbol_listed_on_one_venue_only_evaluates_nothing():
    clock = SimClock(0.0)
    cfg = make_cfg(venue("A", symbols=("BTC-USD", "ETH-USDT")), venue("B", symbols=("BTC-USDT", "ETH-USDT")))
    scanner = CrossVenueScanner(cfg, clock)
    pf = Portfolio({v: {"USD": 1e6, "USDT": 1e6, "BTC": 100.0} for v in ("A", "B")})
    book = QuoteBook()
    book.update(q("B", 110.00, 110.01, 0.0, symbol="BTC-USDT"))
    assert feed(scanner, book, pf, q("A", 99.99, 100.00, 0.0, symbol="BTC-USD")) == []
    assert scanner.stats.evaluations == 0


def test_stale_quotes_never_produce_signals():
    clock = SimClock(0.0)
    cfg = make_cfg(venue("A"), venue("B"))  # max_quote_age_ms = 1500
    scanner = CrossVenueScanner(cfg, clock)
    pf = rich("A", "B")
    book = QuoteBook()
    book.update(q("B", 100.30, 100.31, 0.0))

    clock.set(1.6)  # B is 1.6 s old -> stale
    assert feed(scanner, book, pf, q("A", 99.99, 100.00, 1.6)) == []
    assert scanner.stats.rejects["stale"] == 2
    assert scanner.stats.evaluations == 0
    assert scanner.evaluate_pair(q("A", 99.99, 100.00, 1.6), q("B", 100.30, 100.31, 0.0), pf) is None

    # the updated quote itself stale (e.g. delivered 1.6 s late) against a fresh counterparty -> nothing
    clock.set(3.2)
    book2 = QuoteBook()
    book2.update(q("B", 100.30, 100.31, 3.2))
    assert scanner.on_quote(q("A", 99.99, 100.00, 1.6), book2, pf) == []
    assert scanner.stats.rejects["stale"] == 4
    assert scanner.stats.evaluations == 0


def test_quote_exactly_at_max_age_is_still_usable():
    clock = SimClock(0.0)
    cfg = make_cfg(venue("A"), venue("B"))
    scanner = CrossVenueScanner(cfg, clock)
    book = QuoteBook()
    book.update(q("B", 100.30, 100.31, 0.0))
    clock.set(1.5)  # age == 1.5 s == max_quote_age_ms
    assert len(feed(scanner, book, rich("A", "B"), q("A", 99.99, 100.00, 1.5))) == 1


def test_disconnected_venue_quotes_are_unusable():
    clock = SimClock(0.0)
    cfg = make_cfg(venue("A"), venue("B"))
    scanner = CrossVenueScanner(cfg, clock)
    book = QuoteBook()
    book.update(q("B", 100.30, 100.31, 0.0))
    book.invalidate_venue("B")  # feed reported disconnect
    assert feed(scanner, book, rich("A", "B"), q("A", 99.99, 100.00, 0.0)) == []
    assert scanner.stats.rejects["no_quote"] == 2


def test_crossed_and_invalid_quotes_are_ignored():
    clock = SimClock(0.0)
    cfg = make_cfg(venue("A"), venue("B"))
    scanner = CrossVenueScanner(cfg, clock)
    pf = rich("A", "B")
    good_a = q("A", 99.99, 100.00, 0.0)
    crossed_b = q("B", 100.30, 100.20, 0.0)  # bid > ask: data glitch
    zero_size_b = q("B", 100.30, 100.31, 0.0, bid_size=0.0)
    assert scanner.evaluate_pair(good_a, crossed_b, pf) is None
    assert scanner.evaluate_pair(good_a, zero_size_b, pf) is None
    assert scanner.evaluate_pair(q("A", 100.00, 99.00, 0.0), q("B", 100.30, 100.31, 0.0), pf) is None

    book = QuoteBook()
    book.update(good_a)
    assert scanner.on_quote(crossed_b, book, pf) == []
    assert scanner.stats.rejects["invalid"] == 2
    assert scanner.stats.evaluations == 0


def test_superseded_update_is_ignored():
    clock = SimClock(0.0)
    cfg = make_cfg(venue("A"), venue("B"))
    scanner = CrossVenueScanner(cfg, clock)
    pf = rich("A", "B")
    book = QuoteBook()
    book.update(q("B", 100.30, 100.31, 0.0))
    book.update(q("A", 100.10, 100.11, 0.0, seq=7))
    old = q("A", 99.99, 100.00, 0.0, seq=6)  # out of order: the book rejects it
    assert book.update(old) is False
    assert scanner.on_quote(old, book, pf) == []
    assert scanner.stats.rejects == {"superseded": 1}


# --------------------------------------------------------------------------- cross venue: timers


def test_persistence_requires_continuous_qualification():
    clock = SimClock(0.0)
    cfg = make_cfg(venue("A"), venue("B"), persistence_ms=200.0, cooldown_ms=1000.0)
    scanner = CrossVenueScanner(cfg, clock)
    pf = rich("A", "B")
    book = QuoteBook()
    book.update(q("B", 100.30, 100.31, 0.0))

    assert feed(scanner, book, pf, q("A", 99.99, 100.00, 0.0)) == []  # qualifies from t=0
    clock.set(0.1)
    assert feed(scanner, book, pf, q("A", 99.99, 100.00, 0.1)) == []  # 100 ms < 200 ms
    clock.set(0.15)
    assert feed(scanner, book, pf, q("A", 100.19, 100.20, 0.15)) == []  # edge gone: run broken
    clock.set(0.25)
    assert feed(scanner, book, pf, q("A", 99.99, 100.00, 0.25)) == []  # new run starts at 0.25
    clock.set(0.4)
    assert feed(scanner, book, pf, q("A", 99.99, 100.00, 0.4)) == []  # 150 ms into the new run
    clock.set(0.45)
    out = feed(scanner, book, pf, q("A", 99.99, 100.00, 0.45))  # exactly 200 ms
    assert len(out) == 1 and out[0].ts == 0.45
    assert scanner.stats.rejects["persistence"] == 4
    assert scanner.stats.rejects["below_threshold"] >= 1
    assert scanner.stats.emitted == 1


def test_cooldown_suppresses_the_pair_then_releases():
    clock = SimClock(0.0)
    cfg = make_cfg(venue("A"), venue("B"), persistence_ms=0.0, cooldown_ms=1000.0)
    scanner = CrossVenueScanner(cfg, clock)
    pf = rich("A", "B")
    book = QuoteBook()

    book.update(q("B", 100.30, 100.31, 0.0))
    assert len(feed(scanner, book, pf, q("A", 99.99, 100.00, 0.0))) == 1  # fires at once
    clock.set(0.5)
    book.update(q("B", 100.30, 100.31, 0.5))
    assert feed(scanner, book, pf, q("A", 99.99, 100.00, 0.5)) == []
    clock.set(0.999)
    assert feed(scanner, book, pf, q("A", 99.99, 100.00, 0.999)) == []
    clock.set(1.0)
    out = feed(scanner, book, pf, q("A", 99.99, 100.00, 1.0))  # cooldown ended at 0.0 + 1.0
    assert len(out) == 1 and out[0].market == "BTC-USDT buy@A sell@B"
    assert scanner.stats.rejects["cooldown"] == 2
    assert scanner.stats.emitted == 2


def test_cooldown_is_per_direction_and_does_not_block_the_reverse_pair():
    clock = SimClock(0.0)
    cfg = make_cfg(venue("A"), venue("B"), cooldown_ms=1000.0)
    scanner = CrossVenueScanner(cfg, clock)
    pf = rich("A", "B")
    book = QuoteBook()
    book.update(q("B", 100.30, 100.31, 0.0))
    assert feed(scanner, book, pf, q("A", 99.99, 100.00, 0.0))[0].market == "BTC-USDT buy@A sell@B"
    clock.set(0.2)
    # prices flip: now buy B (99.70) and sell A (100.00) is a 30 bps edge
    out = feed(scanner, book, pf, q("B", 99.69, 99.70, 0.2))
    assert len(out) == 1 and out[0].market == "BTC-USDT buy@B sell@A"


# --------------------------------------------------------------------------- cross venue: sizing


def test_size_capped_by_buying_power_at_slippage_adjusted_price_including_fee():
    clock = SimClock(0.0)
    cfg = make_cfg(venue("A"), venue("B"))
    scanner = CrossVenueScanner(cfg, clock)
    pf = Portfolio({"A": {"USDT": 150.0}, "B": {"BTC": 100.0}})
    sig = scanner.evaluate_pair(q("A", 99.99, 100.00, 0.0, ask_size=20.0), q("B", 100.30, 100.31, 0.0, bid_size=20.0), pf)
    # unit cost = 100 * (1 + 5bps max_slippage) * (1 + 10bps fee) = 100.15005
    # 150 / 100.15005 = 1.49775..., floored to lot 0.001 -> 1.497
    assert sig is not None
    assert sig.size == pytest.approx(1.497)
    assert sig.expected_pnl == pytest.approx(1.497 * (100.30 * 0.9989 - 100.00 * 1.0011))


def test_size_capped_by_sellable_base_on_sell_venue():
    clock = SimClock(0.0)
    cfg = make_cfg(venue("A"), venue("B"))
    scanner = CrossVenueScanner(cfg, clock)
    pf = Portfolio({"A": {"USDT": 1e6}, "B": {"BTC": 0.4}})
    sig = scanner.evaluate_pair(q("A", 99.99, 100.00, 0.0, ask_size=20.0), q("B", 100.30, 100.31, 0.0, bid_size=20.0), pf)
    assert sig is not None and sig.size == pytest.approx(0.4)
    # BTC on the BUY venue does not count as sellable on the sell venue
    pf2 = Portfolio({"A": {"USDT": 1e6, "BTC": 50.0}, "B": {"USDT": 1e6}})
    assert scanner.evaluate_pair(q("A", 99.99, 100.00, 0.0), q("B", 100.30, 100.31, 0.0), pf2) is None


def test_size_capped_by_max_order_notional():
    clock = SimClock(0.0)
    cfg = make_cfg(venue("A"), venue("B"))
    scanner = CrossVenueScanner(cfg, clock)
    # 0.5 * min(20, 30) = 10 BTC, but max_order_notional 500 / ask 100 = 5 BTC
    sig = scanner.evaluate_pair(
        q("A", 99.99, 100.00, 0.0, ask_size=20.0), q("B", 100.30, 100.31, 0.0, bid_size=30.0), rich("A", "B"))
    assert sig is not None and sig.size == pytest.approx(5.0)


def test_size_floored_to_both_venues_lots():
    clock = SimClock(0.0)
    cfg = make_cfg(venue("A", lot=0.001), venue("B", lot=0.01))
    scanner = CrossVenueScanner(cfg, clock)
    # 0.5 * 2.469 = 1.2345 -> on A's grid 1.234, but B needs 0.01 steps -> 1.23
    sig = scanner.evaluate_pair(
        q("A", 99.99, 100.00, 0.0, ask_size=2.469), q("B", 100.30, 100.31, 0.0, bid_size=9.0), rich("A", "B"))
    assert sig is not None and sig.size == pytest.approx(1.23)

    # non-nested lots 0.002 and 0.003: both grids meet every 0.006; 0.1 -> 16 * 0.006 = 0.096
    cfg2 = make_cfg(venue("A", lot=0.002), venue("B", lot=0.003))
    sig2 = CrossVenueScanner(cfg2, clock).evaluate_pair(
        q("A", 99.99, 100.00, 0.0, ask_size=0.2), q("B", 100.30, 100.31, 0.0, bid_size=9.0), rich("A", "B"))
    assert sig2 is not None and sig2.size == pytest.approx(0.096)
    assert round(sig2.size / 0.002, 9).is_integer() and round(sig2.size / 0.003, 9).is_integer()


def test_common_lot():
    assert common_lot(0.001, 0.01) == 0.01
    assert common_lot(0.002, 0.003) == pytest.approx(0.006)
    assert common_lot(0.00001, 0.0001) == 0.0001
    assert common_lot(0.5, 1.0) == 1.0


def test_below_min_notional_is_rejected_on_either_venue():
    clock = SimClock(0.0)
    pf = Portfolio({"A": {"USDT": 1e6}, "B": {"BTC": 0.4}})  # size capped at 0.4 BTC
    buy, sell = q("A", 99.99, 100.00, 0.0), q("B", 100.30, 100.31, 0.0)
    # sell leg notional 0.4 * 100.30 = 40.12 < 50
    assert CrossVenueScanner(make_cfg(venue("A"), venue("B", min_notional=50.0)), clock).evaluate_pair(buy, sell, pf) is None
    # buy leg notional 0.4 * 100.00 = 40.00 < 40.01
    assert CrossVenueScanner(make_cfg(venue("A", min_notional=40.01), venue("B")), clock).evaluate_pair(buy, sell, pf) is None
    # 40.00 >= 40.00 passes
    sig = CrossVenueScanner(make_cfg(venue("A", min_notional=40.0), venue("B", min_notional=40.12)), clock)
    assert sig.evaluate_pair(buy, sell, pf) is not None


def test_no_inventory_means_no_signal():
    clock = SimClock(0.0)
    scanner = CrossVenueScanner(make_cfg(venue("A"), venue("B")), clock)
    book = QuoteBook()
    book.update(q("B", 100.30, 100.31, 0.0))
    assert feed(scanner, book, Portfolio(), q("A", 99.99, 100.00, 0.0)) == []
    assert scanner.stats.rejects["no_size"] == 1


# --------------------------------------------------------------------------- cross venue: multi-venue


def test_best_net_pair_wins_with_three_venues_and_only_updated_venue_pairs_are_evaluated():
    clock = SimClock(0.0)
    # C is expensive to trade: cost(A->C) = 10 + 15 + 1 + 2 = 28 bps
    cfg = make_cfg(venue("A"), venue("B"), venue("C", fee=15.0, slip=2.0))
    scanner = CrossVenueScanner(cfg, clock)
    pf = rich("A", "B", "C")
    book = QuoteBook()
    book.update(q("B", 100.32, 100.33, 0.0))  # A->B: gross 32, cost 22, net 10
    book.update(q("C", 100.36, 100.37, 0.0))  # A->C: gross 36, cost 28, net 8
    out = feed(scanner, book, pf, q("A", 99.99, 100.00, 0.0))
    assert len(out) == 1
    assert out[0].market == "BTC-USDT buy@A sell@B"  # best NET, not best gross
    assert out[0].net_edge_bps == pytest.approx(10.0)
    # A<->B and A<->C in both directions: 4 evaluations, not the 6 of all pairs
    assert scanner.stats.evaluations == 4
    assert scanner.stats.candidates == 2
    assert scanner.stats.emitted == 1
    assert scanner.stats.best_gross_bps == pytest.approx(36.0)
    assert scanner.stats.best_net_bps == pytest.approx(10.0)


def test_pairs_not_involving_the_updated_venue_are_not_evaluated():
    clock = SimClock(0.0)
    cfg = make_cfg(venue("A"), venue("B"), venue("C"), venue("D"))
    scanner = CrossVenueScanner(cfg, clock)
    pf = rich("A", "B", "C", "D")
    book = QuoteBook()
    book.update(q("B", 99.90, 99.95, 0.0))
    book.update(q("C", 100.40, 100.41, 0.0))  # B->C would be 45 bps gross, but A is what updated
    book.update(q("D", 100.00, 100.01, 0.0))
    out = feed(scanner, book, pf, q("A", 99.99, 100.00, 0.0))
    assert [s.market for s in out] == ["BTC-USDT buy@A sell@C"]  # gross 40, net 18
    assert out[0].net_edge_bps == pytest.approx(18.0)
    assert scanner.stats.evaluations == 6  # 3 counterparties x 2 directions
    assert scanner.stats.best_gross_bps == pytest.approx(40.0)


# --------------------------------------------------------------------------- stats


def test_stats_summary_histograms():
    clock = SimClock(0.0)
    cfg = make_cfg(venue("A"), venue("B"))
    scanner = CrossVenueScanner(cfg, clock)
    pf = rich("A", "B")
    book = QuoteBook()
    book.update(q("A", 99.99, 100.00, 0.0))

    # u1: A->B gross 28 / net 6 (fires); B->A gross (99.99-100.29)/100.29 = -29.9
    assert len(feed(scanner, book, pf, q("B", 100.28, 100.29, 0.0))) == 1
    clock.set(0.5)
    # u2: A->B gross 6 / net -16; nothing qualifies
    assert feed(scanner, book, pf, q("B", 100.06, 100.07, 0.5)) == []
    clock.set(0.8)
    # u3: A->B gross 60 / net 38 qualifies but the pair is cooling down until 1.0
    assert feed(scanner, book, pf, q("B", 100.60, 100.61, 0.8)) == []
    clock.set(3.0)
    # u4: B's quote is 2.2 s old: stale, nothing evaluated, no histogram entry
    assert feed(scanner, book, pf, q("A", 99.99, 100.00, 3.0)) == []

    labels = ["<-50"] + [f"[{a},{a + 5})" for a in range(-50, 50, 5)] + [">=50"]
    gross = dict.fromkeys(labels, 0)
    gross["[25,30)"] = 1  # 28
    gross["[5,10)"] = 1  # 6
    gross[">=50"] = 1  # 60
    net = dict.fromkeys(labels, 0)
    net["[5,10)"] = 1  # 6
    net["[-20,-15)"] = 1  # -16
    net["[35,40)"] = 1  # 38

    s = scanner.stats.summary()
    assert s["updates"] == 3
    assert s["evaluations"] == 6
    assert s["candidates"] == 2
    assert s["emitted"] == 1
    assert s["rejects"] == {"below_threshold": 4, "cooldown": 1, "stale": 2}
    assert s["gross_edge_bps"] == gross
    assert s["net_edge_bps"] == net
    assert list(s["gross_edge_bps"]) == labels  # ordered low -> high
    assert s["best_gross_bps"] == pytest.approx(60.0)
    assert s["best_net_bps"] == pytest.approx(38.0)


def test_edge_histogram_bins_and_overflow():
    h = EdgeHistogram(lo=-10.0, hi=10.0, width=2.5)
    for x in (-10.01, -10.0, -0.1, 0.0, 2.4, 9.99, 10.0, 1e6):
        h.add(x)
    assert h.summary() == {
        "<-10": 1, "[-10,-7.5)": 1, "[-7.5,-5)": 0, "[-5,-2.5)": 0, "[-2.5,0)": 1,
        "[0,2.5)": 2, "[2.5,5)": 0, "[5,7.5)": 0, "[7.5,10)": 1, ">=10": 2,
    }
    assert h.total == 8


# --------------------------------------------------------------------------- reference lag

REF, TGT = "binance", "coinbase"


def lag_cfg(**lag_kw: float) -> BotConfig:
    """Reference binance BTC-USDT; target coinbase BTC-USD with fee 6 + slip 2 -> round trip 16 bps."""
    lag = ReferenceLagConfig(
        enabled=True, reference_venue=REF, reference_symbol="BTC-USDT", target_venue=TGT, target_symbol="BTC-USD",
        basis_halflife_s=60.0, min_basis_samples=3, entry_threshold_bps=10.0, take_profit_fraction=0.8,
        stop_bps=15.0, max_hold_s=30.0,
    )
    cfg = BotConfig(
        venues=(
            venue(REF, fee=10.0, slip=1.0, symbols=("BTC-USDT",)),
            venue(TGT, fee=6.0, slip=2.0, symbols=("BTC-USD",), lot=0.0001, min_notional=1.0),
        ),
        signal=SignalConfig(min_net_edge_bps=5.0, participation=0.5, cooldown_ms=1000.0),
        reference_lag=replace(lag, **lag_kw),
        risk=RiskConfig(max_order_notional=500.0, max_net_exposure_notional=1000.0, max_quote_age_ms=1500.0),
        execution=ExecutionConfig(max_slippage_bps=5.0, unwind_slippage_bps=50.0),
    )
    validate(cfg)
    return cfg


def ref_q(mid: float, ts: float) -> Quote:
    return Quote(REF, "BTC-USDT", mid, 5.0, mid, 5.0, ts)  # zero-width so mid is exact


def tgt_q(bid: float, ask: float, ts: float, *, size: float = 2.0) -> Quote:
    return Quote(TGT, "BTC-USD", bid, size, ask, size, ts)


def lag_pf(usd: float = 1000.0, btc: float = 0.0) -> Portfolio:
    return Portfolio({TGT: {"USD": usd, "BTC": btc}})


def warm_up(scanner: ReferenceLagScanner, book: QuoteBook, pf: Portfolio, clock: SimClock, n: int = 3) -> None:
    """n target samples at t = 0..n-1 with ref mid 100 and target mid 100.10: premium 10 bps."""
    for t in range(n):
        clock.set(float(t))
        book.update(ref_q(100.0, float(t)))
        assert feed(scanner, book, pf, tgt_q(100.09, 100.11, float(t))) == []


def test_ema_half_life_weighting():
    clock = SimClock(0.0)
    scanner = ReferenceLagScanner(lag_cfg(basis_halflife_s=60.0, min_basis_samples=1000), clock)
    pf, book = lag_pf(), QuoteBook()
    assert scanner.basis_bps is None

    book.update(ref_q(100.0, 0.0))
    feed(scanner, book, pf, tgt_q(100.10, 100.10, 0.0))  # premium 10: first sample initializes
    assert scanner.basis_bps == pytest.approx(10.0)

    clock.set(60.0)  # exactly one half-life later: new sample weight 0.5
    book.update(ref_q(100.0, 60.0))
    feed(scanner, book, pf, tgt_q(100.30, 100.30, 60.0))  # premium 30 -> 10 + 0.5 * (30 - 10) = 20
    assert scanner.basis_bps == pytest.approx(20.0, abs=1e-9)

    clock.set(180.0)  # two half-lives: weight 1 - 0.25 = 0.75
    book.update(ref_q(100.0, 180.0))
    feed(scanner, book, pf, tgt_q(100.00, 100.00, 180.0))  # premium 0 -> 20 + 0.75 * (0 - 20) = 5
    assert scanner.basis_bps == pytest.approx(5.0, abs=1e-9)
    assert scanner.samples == 3

    clock.set(180.0)  # dt = 0: the sample has no weight
    feed(scanner, book, pf, tgt_q(100.50, 100.50, 180.0))
    assert scanner.basis_bps == pytest.approx(5.0, abs=1e-9)


def test_no_signal_during_warmup():
    clock = SimClock(0.0)
    scanner = ReferenceLagScanner(lag_cfg(min_basis_samples=3), clock)
    pf, book = lag_pf(), QuoteBook()
    warm_up(scanner, book, pf, clock, n=2)
    clock.set(2.0)
    book.update(ref_q(100.0, 2.0))
    # a 40 bps dislocation while only 2 samples exist: no signal, it is folded in as sample 3
    assert feed(scanner, book, pf, tgt_q(99.60, 99.70, 2.0)) == []
    assert scanner.samples == 3
    assert scanner.stats.rejects["warmup"] == 3


def test_buy_signal_measured_against_pre_update_basis():
    # half-life 1 s and dt = 1 s: folding the dislocated sample FIRST would halve the basis
    # to (10 + -35) / 2 = -12.5 -> fair 99.875 -> gap 17.55 - 16 = 1.55 bps < 10: no trade.
    clock = SimClock(0.0)
    scanner = ReferenceLagScanner(lag_cfg(basis_halflife_s=1.0), clock)
    pf, book = lag_pf(usd=1000.0), QuoteBook()
    warm_up(scanner, book, pf, clock)
    assert scanner.basis_bps == pytest.approx(10.0)

    clock.set(3.0)
    book.update(ref_q(100.0, 3.0))
    out = feed(scanner, book, pf, tgt_q(99.60, 99.70, 3.0))
    assert len(out) == 1
    sig = out[0]
    # fair = 100 * (1 + 10bps) = 100.10; gap = (100.10 - 99.70) / 99.70 = 40.1204 bps.
    # The edge is to the take-profit target, 0.8 of the gap: 32.0963 bps; net = 32.0963 - 16.
    assert sig.kind is SignalKind.REFERENCE_LAG
    assert sig.market == "BTC-USD buy@coinbase ref BTC-USDT@binance"
    assert sig.gross_edge_bps == pytest.approx(0.8 * 0.40 / 99.70 * 1e4)
    assert sig.gross_edge_bps == pytest.approx((sig.target - sig.entry) / sig.entry * 1e4)
    assert sig.cost_bps == pytest.approx(16.0)
    assert sig.net_edge_bps == pytest.approx(0.8 * 0.40 / 99.70 * 1e4 - 16.0)
    assert sig.entry == 99.70
    assert sig.target == pytest.approx(100.02)  # 99.70 + 0.8 * 0.40
    assert sig.stop == pytest.approx(99.55045)  # 99.70 * (1 - 15bps)
    assert sig.target > sig.entry > sig.stop
    assert sig.max_hold_s == 30.0
    # size = 0.5 * 2.0 = 1.0 (500/99.70 = 5.01 cap; 1000 USD buys ~10.02)
    assert sig.size == pytest.approx(1.0)
    # pnl = 1.0 * (100.02 * (1 - 8bps) - 99.70 * (1 + 8bps)) = 99.939984 - 99.77976
    assert sig.expected_pnl == pytest.approx(0.160224, abs=1e-9)
    (leg,) = sig.legs
    assert (leg.venue, leg.symbol, leg.side, leg.price, leg.size) == (TGT, "BTC-USD", Side.BUY, 99.70, 2.0)
    # THEN the observation was folded: premium (99.65 - 100) / 100 = -35 bps with weight 0.5
    assert scanner.basis_bps == pytest.approx(-12.5, abs=1e-9)
    assert scanner.samples == 4


def test_basis_alpha_for_one_second_at_sixty_second_half_life():
    clock = SimClock(0.0)
    scanner = ReferenceLagScanner(lag_cfg(basis_halflife_s=60.0), clock)
    pf, book = lag_pf(), QuoteBook()
    warm_up(scanner, book, pf, clock)
    clock.set(3.0)
    book.update(ref_q(100.0, 3.0))
    assert len(feed(scanner, book, pf, tgt_q(99.60, 99.70, 3.0))) == 1
    alpha = 1 - 2 ** (-1 / 60)  # = 0.011486...
    assert scanner.basis_bps == pytest.approx(10.0 + alpha * (-35.0 - 10.0))


def test_sell_signal_needs_sellable_base_and_mirrors_target_and_stop():
    clock = SimClock(0.0)
    cfg = lag_cfg()
    pf_none, book = lag_pf(usd=1000.0, btc=0.0), QuoteBook()
    scanner = ReferenceLagScanner(cfg, clock)
    warm_up(scanner, book, pf_none, clock)
    clock.set(3.0)
    book.update(ref_q(100.0, 3.0))
    rich_tgt = tgt_q(100.50, 100.60, 3.0)
    # bid 100.50 > fair 100.10 but there is no BTC on the target venue to sell
    assert feed(scanner, book, pf_none, rich_tgt) == []
    assert scanner.stats.rejects["no_size"] == 1

    scanner2 = ReferenceLagScanner(cfg, clock2 := SimClock(0.0))
    pf, book2 = lag_pf(usd=0.0, btc=0.3), QuoteBook()
    warm_up(scanner2, book2, pf, clock2)
    clock2.set(3.0)
    book2.update(ref_q(100.0, 3.0))
    out = feed(scanner2, book2, pf, tgt_q(100.50, 100.60, 3.0))
    assert len(out) == 1
    sig = out[0]
    assert sig.market == "BTC-USD sell@coinbase ref BTC-USDT@binance"
    assert sig.legs[0].side is Side.SELL and sig.legs[0].price == 100.50
    # gap = (100.50 - 100.10) / 100.50 = 39.801 bps; edge to the target = 0.8 * gap; net = edge - 16
    assert sig.gross_edge_bps == pytest.approx(0.8 * 0.40 / 100.50 * 1e4)
    assert sig.gross_edge_bps == pytest.approx((sig.entry - sig.target) / sig.entry * 1e4)
    assert sig.net_edge_bps == pytest.approx(0.8 * 0.40 / 100.50 * 1e4 - 16.0)
    assert sig.entry == 100.50
    assert sig.target == pytest.approx(100.18)  # 100.50 - 0.8 * 0.40
    assert sig.stop == pytest.approx(100.65075)  # 100.50 * (1 + 15bps)
    assert sig.stop > sig.entry > sig.target
    assert sig.size == pytest.approx(0.3)  # sellable 0.3 < 0.5 * 2.0
    # pnl = 0.3 * (100.50 * (1 - 8bps) - 100.18 * (1 + 8bps)) = 0.3 * (100.4196 - 100.260144)
    assert sig.expected_pnl == pytest.approx(0.0478368, abs=1e-9)


def test_buy_needs_buying_power():
    clock = SimClock(0.0)
    scanner = ReferenceLagScanner(lag_cfg(), clock)
    pf, book = lag_pf(usd=0.0, btc=5.0), QuoteBook()
    warm_up(scanner, book, pf, clock)
    clock.set(3.0)
    book.update(ref_q(100.0, 3.0))
    assert feed(scanner, book, pf, tgt_q(99.60, 99.70, 3.0)) == []


def test_small_deviation_inside_costs_does_not_fire():
    # fair 100.10; ask 100.00 -> gap 10 bps - 16 bps costs = -6 < 10
    clock = SimClock(0.0)
    scanner = ReferenceLagScanner(lag_cfg(), clock)
    pf, book = lag_pf(), QuoteBook()
    warm_up(scanner, book, pf, clock)
    clock.set(3.0)
    book.update(ref_q(100.0, 3.0))
    assert feed(scanner, book, pf, tgt_q(99.98, 100.00, 3.0)) == []
    assert scanner.stats.rejects["below_threshold"] == 1


def test_stale_reference_blocks_signals_and_basis_updates():
    clock = SimClock(0.0)
    scanner = ReferenceLagScanner(lag_cfg(), clock)
    pf, book = lag_pf(), QuoteBook()
    warm_up(scanner, book, pf, clock)  # last ref quote at t=2
    basis = scanner.basis_bps
    clock.set(3.6)  # ref is 1.6 s old
    assert feed(scanner, book, pf, tgt_q(99.60, 99.70, 3.6)) == []
    assert scanner.basis_bps == basis
    assert scanner.samples == 3
    assert scanner.stats.rejects["stale"] == 1

    book.invalidate_venue(REF)  # disconnected reference
    assert feed(scanner, book, pf, tgt_q(99.60, 99.70, 3.6)) == []
    assert scanner.stats.rejects["no_quote"] == 1


def test_reference_move_is_evaluated_against_standing_target_quote_without_folding():
    clock = SimClock(0.0)
    scanner = ReferenceLagScanner(lag_cfg(), clock)
    pf, book = lag_pf(), QuoteBook()
    warm_up(scanner, book, pf, clock)  # target 100.09/100.11 standing since t=2
    basis = scanner.basis_bps
    clock.set(3.0)
    out = feed(scanner, book, pf, ref_q(100.40, 3.0))  # the reference jumps 40 bps
    assert len(out) == 1
    # fair = 100.40 * 1.001 = 100.5004; gap = (100.5004 - 100.11) / 100.11; edge to the target = 0.8 * gap
    assert out[0].legs[0].side is Side.BUY
    assert out[0].gross_edge_bps == pytest.approx(0.8 * (100.40 * 1.001 - 100.11) / 100.11 * 1e4)
    assert scanner.basis_bps == basis and scanner.samples == 3  # reference ticks never fold


def test_reference_lag_cooldown():
    clock = SimClock(0.0)
    scanner = ReferenceLagScanner(lag_cfg(), clock)  # cooldown 1000 ms
    pf, book = lag_pf(usd=10_000.0), QuoteBook()
    warm_up(scanner, book, pf, clock)
    results = []
    for t in (3.0, 3.5, 3.999, 4.0):
        clock.set(t)
        book.update(ref_q(100.0, t))
        results.append(len(feed(scanner, book, pf, tgt_q(99.60, 99.70, t))))
    assert results == [1, 0, 0, 1]
    assert scanner.stats.rejects["cooldown"] == 2
    assert scanner.stats.emitted == 2


def test_reference_lag_ignores_unrelated_quotes_and_disabled_config():
    clock = SimClock(0.0)
    scanner = ReferenceLagScanner(lag_cfg(), clock)
    book = QuoteBook()
    other = Quote(TGT, "ETH-USD", 1.0, 1.0, 1.1, 1.0, 0.0)
    assert scanner.on_quote(other, book, lag_pf()) == []
    assert scanner.samples == 0

    disabled = replace(lag_cfg(), reference_lag=replace(lag_cfg().reference_lag, enabled=False))
    off = ReferenceLagScanner(disabled, clock)
    book.update(ref_q(100.0, 0.0))
    assert feed(off, book, lag_pf(), tgt_q(100.09, 100.11, 0.0)) == []
    assert off.basis_bps is None


def test_reference_lag_ema_math_is_independent_of_absolute_epoch():
    # same weighting at epoch-scale timestamps (float resolution ~0.2 us)
    t0 = 1_700_000_000.0
    clock = SimClock(t0)
    scanner = ReferenceLagScanner(lag_cfg(basis_halflife_s=60.0, min_basis_samples=1000), clock)
    pf, book = lag_pf(), QuoteBook()
    book.update(ref_q(100.0, t0))
    feed(scanner, book, pf, tgt_q(100.10, 100.10, t0))
    clock.set(t0 + 60.0)
    book.update(ref_q(100.0, t0 + 60.0))
    feed(scanner, book, pf, tgt_q(100.30, 100.30, t0 + 60.0))
    assert scanner.basis_bps == pytest.approx(20.0, abs=1e-6)
    clock.set(t0 + 180.0)
    book.update(ref_q(100.0, t0 + 180.0))
    feed(scanner, book, pf, tgt_q(100.00, 100.00, t0 + 180.0))
    alpha = 1 - math.exp(-math.log(2) * 120.0 / 60.0)  # 0.75
    assert scanner.basis_bps == pytest.approx(20.0 + alpha * (0.0 - 20.0), abs=1e-6)


# --------------------------------------------------------------------------- review findings (regressions)


def test_warm_up_median_seed_keeps_one_early_outlier_from_setting_the_basis():
    # README values: half-life 300 s, 100 samples, target quotes at 10 Hz. The first observation is a
    # +100 bps transient; the next 120 are exactly at the reference (premium 0). An EMA seeded with the
    # first sample would still be ~98 bps after 10 s and fire on a perfectly normal quote.
    clock = SimClock(0.0)
    scanner = ReferenceLagScanner(lag_cfg(basis_halflife_s=300.0, min_basis_samples=100), clock)
    pf, book = lag_pf(usd=10_000.0), QuoteBook()
    book.update(ref_q(100.0, 0.0))
    feed(scanner, book, pf, tgt_q(101.0, 101.0, 0.0))
    signals = []
    for i in range(1, 121):
        t = i / 10
        clock.set(t)
        book.update(ref_q(100.0, t))
        signals += feed(scanner, book, pf, tgt_q(99.99, 100.01, t))  # at fair
    assert signals == []
    assert scanner.warm and scanner.samples == 121
    assert scanner.basis_bps == pytest.approx(0.0, abs=1e-12)  # median of [100, 0 x 99], then zeros


def test_same_time_observations_carry_no_weight_and_are_not_counted():
    clock = SimClock(0.0)
    scanner = ReferenceLagScanner(lag_cfg(min_basis_samples=3), clock)
    pf, book = lag_pf(), QuoteBook()
    book.update(ref_q(100.0, 0.0))
    for _ in range(5):  # five target quotes stamped t=0
        feed(scanner, book, pf, tgt_q(100.09, 100.11, 0.0))
    assert scanner.samples == 1 and not scanner.warm


def test_reference_lag_edge_is_measured_to_the_take_profit_target():
    # fair 100.10 (basis 10 bps), costs 16 bps, threshold 10, take-profit 0.8 of the gap.
    # ask 99.78: gap 32.07 bps; gap - 16 = 16.07 would pass, but the target is only 0.8 of the way:
    # 0.8 * 32.07 - 16 = 9.66 < 10 -> no trade.
    clock = SimClock(0.0)
    scanner = ReferenceLagScanner(lag_cfg(), clock)
    pf, book = lag_pf(usd=1000.0), QuoteBook()
    warm_up(scanner, book, pf, clock)
    clock.set(3.0)
    book.update(ref_q(100.0, 3.0))
    assert feed(scanner, book, pf, tgt_q(99.70, 99.78, 3.0)) == []
    assert scanner.stats.rejects["below_threshold"] == 1

    clock2 = SimClock(0.0)
    scanner2 = ReferenceLagScanner(lag_cfg(), clock2)
    book2 = QuoteBook()
    warm_up(scanner2, book2, pf, clock2)
    clock2.set(3.0)
    book2.update(ref_q(100.0, 3.0))
    (sig,) = feed(scanner2, book2, pf, tgt_q(99.60, 99.70, 3.0))
    # The promised net edge is what the signal's own target and costs imply (to second order).
    implied = sig.expected_pnl / (sig.size * sig.entry) * 1e4
    assert sig.net_edge_bps == pytest.approx(implied, abs=0.1)
    assert sig.net_edge_bps >= 10.0
