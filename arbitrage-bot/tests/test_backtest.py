"""Tests for arbbot.backtest: replay through the real bot, paper fills at arrival, exact accounting.

Two hand-worked scenarios pin the numbers:

* ``kill_switch``: an arb whose sell leg, hedge and unwind all miss leaves a
  +1 BTC residual; the kill switch trips and the next signal is rejected.
* ``crash``: a reference-lag long is stopped out during a stepwise crash in
  which every exit expires, so the monitor gives up with RESIDUAL.

Synthetic data (``generate_synthetic``) checks the end-to-end behaviour: profit
from dislocations, zero trades without them, reconciliation and determinism.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path

import pytest

from arbbot.backtest import BacktestResult, run_backtest, run_backtest_async
from arbbot.config import (
    BotConfig,
    InstrumentConfig,
    ReferenceLagConfig,
    RiskConfig,
    SignalConfig,
    VenueConfig,
)
from arbbot.feeds.replay import generate_synthetic
from arbbot.journal import Journal
from arbbot.models import Quote

SYM = "BTC-USDT"
START = 1767225600.0  # 2026-01-01T00:00:00Z
ABS = 1e-9


def arb_cfg(**signal_kw: float) -> BotConfig:
    inst = InstrumentConfig(SYM, "BTCUSDT", tick_size=0.01, lot_size=0.00001, min_notional=5.0)
    bal = {"USDT": 10_000.0, "BTC": 0.2}
    return BotConfig(
        venues=(
            VenueConfig("binance", "binance", taker_fee_bps=10.0, instruments=(inst,), starting_balances=bal),
            VenueConfig("bybit", "bybit", taker_fee_bps=10.0, instruments=(inst,), starting_balances=bal),
        ),
        signal=SignalConfig(**signal_kw),
    )


def synth(*, dislocation_rate: float, seed: int = 7, duration_s: float = 600.0) -> list[Quote]:
    return generate_synthetic(
        ["binance", "bybit"], SYM, start_ts=START, duration_s=duration_s, hz=10, base_price=50_000.0,
        vol_bps=2.0, spread_bps=1.0, depth=1.0, dislocation_rate=dislocation_rate, dislocation_bps=40.0,
        seed=seed,
    )


def equity_at(balances: dict[str, dict[str, float]], marks: dict[str, float]) -> float:
    return sum(q * marks.get(a, 0.0) for assets in balances.values() for a, q in assets.items())


def assert_reconciles(r: BacktestResult, cfg: BotConfig) -> None:
    """final - initial equity (both at the final marks) == realized PnL + residual MTM, recomputed here."""
    initial = equity_at({v.name: dict(v.starting_balances) for v in cfg.venues}, r.final_marks)
    final = equity_at(r.final_portfolio, r.final_marks)
    assert initial == pytest.approx(r.initial_equity, abs=1e-9)
    assert final == pytest.approx(r.final_equity, abs=1e-9)
    assert abs((final - initial) - (r.net_pnl + r.residual_mtm)) < 1e-6
    assert abs(r.reconciliation_error) < 1e-6
    if r.equity_curve:  # the last point is taken at the final marks
        assert r.equity_curve[-1].pnl == pytest.approx(final - initial, abs=1e-6)


# --------------------------------------------------------------------------- synthetic data


def test_dislocations_produce_profitable_trades_and_equity_reconciles() -> None:
    cfg = arb_cfg()
    r = run_backtest(cfg, synth(dislocation_rate=0.02))

    assert r.events == 12_000 and r.skipped_events == 0
    assert r.trades >= 3 and r.closed_trades == r.trades
    assert r.outcomes == {"completed": r.trades}  # synthetic dislocations last >= 0.2 s > 50 ms latency
    assert r.signals == r.approved == r.trades and r.rejections == {}
    assert r.net_pnl > 0 and r.hit_rate == 1.0
    assert r.mean_realized_edge_bps is not None and r.mean_realized_edge_bps > 0
    assert r.mean_signal_net_edge_bps is not None and r.mean_signal_net_edge_bps >= 5.0  # X
    # 10 bps taker on each leg: fees are 0.1% of both legs' notional, all realized.
    assert r.gross_pnl - r.fees == pytest.approx(r.net_pnl, abs=1e-9)
    assert r.residual_mtm == pytest.approx(0.0, abs=1e-6) and r.residual_inventory == {}
    assert not r.halted and r.open_positions == 0
    assert_reconciles(r, cfg)
    # Hedged arbs move inventory between venues but leave total BTC unchanged.
    btc = sum(a.get("BTC", 0.0) for a in r.final_portfolio.values())
    assert btc == pytest.approx(0.4, abs=1e-9)
    assert r.scanner["emitted"] == r.signals and r.scanner["evaluations"] > 0
    assert r.pnl_by_quote == {"USDT": pytest.approx(r.net_pnl)}


def test_no_dislocations_means_no_trades() -> None:
    cfg = arb_cfg()
    r = run_backtest(cfg, synth(dislocation_rate=0.0))
    assert r.events == 12_000
    assert (r.signals, r.trades, r.approved) == (0, 0, 0)
    assert r.outcomes == {} and r.rejections == {}
    assert r.net_pnl == 0.0 and r.fees == 0.0 and r.residual_mtm == 0.0
    assert r.final_equity == r.initial_equity and r.reconciliation_error == 0.0
    assert r.max_drawdown == 0.0 and all(p.pnl == 0.0 for p in r.equity_curve)
    assert r.final_portfolio == {"binance": {"BTC": 0.2, "USDT": 10_000.0}, "bybit": {"BTC": 0.2, "USDT": 10_000.0}}
    # Noise is ~0.5 bps per venue: the best gross edge never gets near the 20 bps of fees.
    assert r.scanner["best_net_bps"] < -10.0
    assert r.hit_rate is None and r.mean_realized_edge_bps is None


def test_two_runs_are_identical() -> None:
    cfg = arb_cfg()
    quotes = synth(dislocation_rate=0.03, seed=3)
    a = run_backtest(cfg, quotes)
    b = run_backtest(cfg, list(quotes))
    assert a.trades > 0
    assert a == b
    assert json.dumps(a.to_dict(), sort_keys=True) == json.dumps(b.to_dict(), sort_keys=True)


async def test_async_entry_point_matches_sync() -> None:
    cfg = arb_cfg()
    quotes = synth(dislocation_rate=0.02, duration_s=120.0)
    r = await run_backtest_async(cfg, quotes)
    assert r.events == 2_400 and abs(r.reconciliation_error) < 1e-6
    assert r == await asyncio.to_thread(run_backtest, cfg, quotes)  # sync wrapper, own event loop


def test_quotes_for_unconfigured_venues_are_skipped() -> None:
    cfg = arb_cfg()
    quotes = synth(dislocation_rate=0.0, duration_s=10.0)
    extra = [dataclasses.replace(q, venue="kraken") for q in quotes[:5]]
    r = run_backtest(cfg, quotes + extra)
    assert r.events == len(quotes) and r.skipped_events == 5


def test_journal_logs_every_signal_with_its_decision(tmp_path: Path) -> None:
    cfg = arb_cfg()
    path = tmp_path / "journal.jsonl"
    journal = Journal(path)
    r = run_backtest(cfg, synth(dislocation_rate=0.02), journal=journal)
    journal.close()
    recs = [json.loads(line) for line in path.read_text().splitlines()]
    kinds = [x["kind"] for x in recs]
    assert kinds[0] == "start" and kinds[-1] == "shutdown"  # the run is bracketed in the journal
    assert recs[0]["mode"] == "backtest" and recs[0]["events"] == r.events
    assert set(kinds[1:-1]) == {"signal", "risk", "execution"}
    for i, rec in enumerate(recs):
        if rec["kind"] == "signal":
            sig = rec["signal"]
            assert sig["kind"] == "cross_venue" and sig["net_edge_bps"] >= 5.0
            decision = recs[i + 1]
            assert decision["kind"] == "risk" and decision["signal_id"] == sig["id"]
            assert decision["approved"] is True and decision["reason"] == "ok"
            execution = recs[i + 2]
            assert execution["kind"] == "execution" and execution["signal_id"] == sig["id"]
    assert kinds.count("signal") == kinds.count("risk") == r.signals
    assert kinds.count("execution") == sum(r.outcomes.values())


# --------------------------------------------------------------------------- kill switch (hand-worked)

T0 = 1000.0


def kill_switch_cfg() -> BotConfig:
    """A (10 ms) holds 1000 USDT, B (100 ms) holds 1 BTC; 10 bps taker, no slippage, lot 0.001."""
    inst = InstrumentConfig(SYM, "BTCUSDT", tick_size=0.01, lot_size=0.001, min_notional=1.0)
    return BotConfig(
        venues=(
            VenueConfig("A", "binance", taker_fee_bps=10.0, slippage_bps=0.0, latency_ms=10.0,
                        instruments=(inst,), starting_balances={"USDT": 1000.0}),
            VenueConfig("B", "bybit", taker_fee_bps=10.0, slippage_bps=0.0, latency_ms=100.0,
                        instruments=(inst,), starting_balances={"BTC": 1.0}),
        ),
        signal=SignalConfig(min_net_edge_bps=5.0, participation=0.5, cooldown_ms=0.0),
        risk=RiskConfig(min_top_depth_notional=100.0),
    )


def kq(venue: str, t: float, bid: float, ask: float) -> Quote:
    return Quote(venue, SYM, bid, 5.0, ask, 5.0, T0 + t)


KILL_SWITCH_QUOTES = [kq("A", 0.0, 99.99, 100.00), kq("B", 0.001, 99.99, 100.00), kq("B", 1.0, 100.40, 100.41),
                      kq("B", 1.05, 99.80, 99.81), kq("B", 1.12, 99.70, 99.75), kq("A", 1.15, 99.40, 99.50),
                      kq("B", 2.0, 100.20, 100.21)]


def test_residual_trips_the_kill_switch_and_blocks_the_next_signal(tmp_path: Path) -> None:
    """Hand-worked timeline.

    t=1.000 B bid 100.40 vs A ask 100.00: gross 40 bps - 20 bps fees = net 20 -> signal, size
            min(0.5 * 5, 500/100, buying power 9.98, B's 1 BTC) = 1.0.
            BUY A limit floor(100.05) arrives 1.010: fills 1.0 @ 100.00, fee 0.10.
            SELL B limit ceil(100.3498) = 100.35 arrives 1.100: B bid is 99.80 (t=1.05) -> expires.
            hedge SELL B, sent at 1.100: priced from the newest B quote received by then (t=1.05, bid
                99.80), not the signal's: limit max(ceil(99.80 * 0.9995) = 99.76, band 99.50) = 99.76.
                It arrives 1.200: B bid is 99.70 (t=1.12) -> expires.
            unwind SELL A: limit 99.50 (entry - 50 bps), arrives 1.210: A bid 99.40 (t=1.15) -> expires.
            RESIDUAL +1.0 marked at A's mid as of 1.210 (t=1.15 quote) 99.45:
                realized = -100.00 - 0.10 + 99.45 = -0.65.
    The B (t=1.05, t=1.12) and A (t=1.15) quotes arrive while the execution runs and fire nothing.
    t=2.000 B bid 100.20 vs A ask 99.50: net 50.35 bps -> signal -> rejected "halted:residual".
    Final marks: A mid 99.45, B mid 100.205 -> BTC 99.8275. Equity 1099.8275 -> 1099.555 (-0.2725)
    = net -0.65 + residual MTM (1.0 * 99.8275 - 99.45 = +0.3775).
    """
    cfg = kill_switch_cfg()
    path = tmp_path / "j.jsonl"
    journal = Journal(path)
    r = run_backtest(cfg, KILL_SWITCH_QUOTES, journal=journal)
    journal.close()

    assert r.halted and r.halt_reason == "residual"
    assert (r.signals, r.approved) == (2, 1)
    assert r.outcomes == {"residual": 1}
    assert r.rejections == {"halted:residual": 1}
    assert (r.trades, r.closed_trades, r.hit_rate) == (1, 0, None)
    (rep,) = [json.loads(x) for x in path.read_text().splitlines() if json.loads(x)["kind"] == "execution"]
    assert [(o["venue"], o["side"], o["filled_qty"], o["ts"]) for o in rep["orders"]] == [
        ("A", "buy", 1.0, pytest.approx(T0 + 1.01)), ("B", "sell", 0.0, pytest.approx(T0 + 1.1)),
        ("B", "sell", 0.0, pytest.approx(T0 + 1.2)), ("A", "sell", 0.0, pytest.approx(T0 + 1.21)),
    ]
    assert rep["notes"] == ["hedge sell 1 on B @<= 99.76: expired 0", "unwind sell 1 on A @<= 99.5: expired 0",
                            "residual +1 marked at mid 99.45"]
    assert r.fees == pytest.approx(0.10, abs=ABS)
    assert r.net_pnl == pytest.approx(-0.65, abs=ABS)
    assert r.gross_pnl == pytest.approx(-0.55, abs=ABS)
    assert r.final_marks["BTC"] == pytest.approx(99.8275, abs=ABS)
    assert r.residual_mtm == pytest.approx(0.3775, abs=ABS)
    assert r.residual_inventory == {"BTC": pytest.approx(1.0)}
    assert r.initial_equity == pytest.approx(1099.8275, abs=ABS)
    assert r.final_equity == pytest.approx(1099.555, abs=ABS)
    assert r.final_portfolio == {"A": {"BTC": pytest.approx(1.0), "USDT": pytest.approx(899.9)},
                                 "B": {"BTC": pytest.approx(1.0)}}
    assert_reconciles(r, cfg)


# --------------------------------------------------------------------------- monitor RESIDUAL (hand-worked)


def crash_cfg() -> BotConfig:
    ri = InstrumentConfig("BTC-USDT", "BTCUSDT", tick_size=0.01, lot_size=0.001, min_notional=1.0)
    ti = InstrumentConfig("BTC-USD", "BTC-USD", tick_size=0.01, lot_size=0.001, min_notional=1.0)
    return BotConfig(
        venues=(
            VenueConfig("R", "binance", taker_fee_bps=10.0, slippage_bps=0.0, latency_ms=10.0,
                        instruments=(ri,), starting_balances={"USDT": 1000.0}),
            VenueConfig("T", "coinbase", taker_fee_bps=10.0, slippage_bps=0.0, latency_ms=10.0,
                        instruments=(ti,), starting_balances={"USD": 1000.0}),
        ),
        signal=SignalConfig(cooldown_ms=0.0),
        risk=RiskConfig(min_top_depth_notional=10.0),
        reference_lag=ReferenceLagConfig(
            enabled=True, reference_venue="R", reference_symbol="BTC-USDT", target_venue="T",
            target_symbol="BTC-USD", basis_halflife_s=60.0, min_basis_samples=1, entry_threshold_bps=5.0,
            take_profit_fraction=0.8, stop_bps=15.0, max_hold_s=30.0,
        ),
    )


def cq(venue: str, t: float, bid: float, ask: float) -> Quote:
    return Quote(venue, "BTC-USDT" if venue == "R" else "BTC-USD", bid, 1.0, ask, 1.0, T0 + t)


def test_reference_lag_stop_during_a_crash_ends_residual_and_reconciles() -> None:
    """Hand-worked timeline (target T, 10 ms latency, 10 bps fee, max 5 exit attempts).

    Basis 0 after the first T quote. t=1.000 T ask 99.42 vs fair 100.01: BUY, size 0.5,
    stop 99.42 * (1 - 15 bps) = 99.2709. Fills 0.5 @ 99.42, entry fee 0.04971.
    Each later T quote is >= 50 bps below the previous one, so every exit (limit = bid - 50 bps,
    tick-rounded up) arrives to an even lower bid and expires: 5 NO_FILLs, then the monitor
    emits RESIDUAL marked at the last mid used, 96.51:
        realized = 0.5 * (96.51 - 99.42) - 0.04971 = -1.50471
    Signals during the exit are rejected by max_open_positions (4), then by the kill switch (2).
    Final marks: BTC = mean(R mid 100.01, T mid 95.91) = 97.96.
    Equity 2000 -> 2000 - 49.75971 + 0.5 * 97.96 = 1999.22029 (-0.77971)
    = net -1.50471 + residual MTM (0.5 * 97.96 - 0.5 * 96.51 = 0.725).
    """
    cfg = crash_cfg()
    quotes = [cq("R", 0.0, 100.00, 100.02), cq("T", 0.001, 100.00, 100.02), cq("T", 1.0, 99.40, 99.42),
              cq("T", 1.02, 98.90, 98.92), cq("T", 1.025, 98.30, 98.32), cq("T", 1.035, 97.70, 97.72),
              cq("T", 1.045, 97.10, 97.12), cq("T", 1.055, 96.50, 96.52), cq("T", 1.065, 95.90, 95.92)]
    r = run_backtest(cfg, quotes)

    assert r.outcomes == {"no_fill": 5, "opened": 1, "residual": 1}
    assert r.rejections == {"halted:residual": 2, "max_open_positions": 4}
    assert r.halted and r.halt_reason == "residual"
    assert (r.signals, r.approved, r.trades, r.closed_trades, r.open_positions) == (7, 1, 1, 0, 0)
    assert r.fees == pytest.approx(0.04971, abs=ABS)
    assert r.net_pnl == pytest.approx(-1.50471, abs=ABS)
    assert r.gross_pnl == pytest.approx(-1.455, abs=ABS)
    assert r.final_marks == {"BTC": pytest.approx(97.96), "USD": 1.0, "USDT": 1.0}
    assert r.residual_mtm == pytest.approx(0.725, abs=ABS)
    assert r.residual_inventory == {"BTC": pytest.approx(0.5)}
    assert r.initial_equity == pytest.approx(2000.0, abs=ABS)
    assert r.final_equity == pytest.approx(1999.22029, abs=ABS)
    assert r.pnl_by_quote == {"USD": pytest.approx(-1.50471, abs=ABS)}
    assert r.reference_lag is not None and r.reference_lag["emitted"] == 7
    assert_reconciles(r, cfg)


# --------------------------------------------------------------------------- reference lag on synthetic data


def lag_cfg() -> BotConfig:
    ref_i = InstrumentConfig("BTC-USDT", "BTCUSDT", tick_size=0.01, lot_size=0.00001, min_notional=5.0)
    tgt_i = InstrumentConfig("BTC-USD", "BTC-USD", tick_size=0.01, lot_size=0.00001, min_notional=5.0)
    return BotConfig(
        venues=(
            VenueConfig("ref", "binance", taker_fee_bps=10.0, instruments=(ref_i,),
                        starting_balances={"USDT": 10_000.0, "BTC": 0.2}),
            VenueConfig("tgt", "coinbase", taker_fee_bps=5.0, instruments=(tgt_i,),
                        starting_balances={"USD": 10_000.0, "BTC": 0.2}),
        ),
        reference_lag=ReferenceLagConfig(
            enabled=True, reference_venue="ref", reference_symbol="BTC-USDT", target_venue="tgt",
            target_symbol="BTC-USD", basis_halflife_s=60.0, min_basis_samples=50, entry_threshold_bps=5.0,
            take_profit_fraction=0.8, stop_bps=30.0, max_hold_s=5.0,
        ),
    )


def lag_quotes() -> list[Quote]:
    raw = generate_synthetic(
        ["ref", "tgt"], "BTC-USDT", start_ts=START, duration_s=600, hz=10, base_price=50_000.0,
        vol_bps=2.0, spread_bps=1.0, depth=1.0, dislocation_rate=0.03, dislocation_bps=40.0, seed=11,
    )
    return [dataclasses.replace(q, symbol="BTC-USD") if q.venue == "tgt" else q for q in raw]


def test_reference_lag_round_trips_and_open_positions_reconcile(tmp_path: Path) -> None:
    cfg, quotes = lag_cfg(), lag_quotes()
    path = tmp_path / "j.jsonl"
    journal = Journal(path)
    full = run_backtest(cfg, quotes, journal=journal)
    journal.close()
    assert full.outcomes.get("opened", 0) >= 3
    assert full.outcomes["opened"] == full.outcomes["closed"]  # every position closed by stop/target/time
    assert full.open_positions == 0 and full.residual_mtm == pytest.approx(0.0, abs=1e-6)
    assert full.gross_pnl - full.fees == pytest.approx(full.net_pnl, abs=1e-9)
    assert_reconciles(full, cfg)

    # Cut the data right after the last entry: that position is still open at the end.
    recs = [json.loads(line) for line in path.read_text().splitlines()]
    last_open = max(x["finished_ts"] for x in recs if x["kind"] == "execution" and x["outcome"] == "opened")
    cut = run_backtest(cfg, [q for q in quotes if q.ts_local <= last_open + 0.3])
    assert cut.open_positions == 1
    assert cut.trades == cut.closed_trades + 1
    assert cut.residual_mtm != pytest.approx(0.0, abs=1e-6)
    assert sum(cut.residual_inventory.values()) != 0.0
    # The open position's entry fee is paid but not yet realized: gross excludes it.
    assert cut.gross_pnl < cut.net_pnl + cut.fees
    assert_reconciles(cut, cfg)


def test_empty_input() -> None:
    r = run_backtest(arb_cfg(), [])
    assert (r.events, r.signals, r.trades) == (0, 0, 0)
    assert r.start_ts is None and r.equity_curve == [] and r.reconciliation_error == 0.0
    assert "0 quotes" in r.format_report()


def test_report_mentions_the_key_numbers() -> None:
    cfg = kill_switch_cfg()
    text = run_backtest(cfg, KILL_SWITCH_QUOTES).format_report()
    assert "TRIPPED: residual" in text
    assert "halted:residual 1" in text
    assert "net -0.6500" in text and "residual MTM +0.3775" in text
    assert "not flat    {'BTC': 1.0}" in text


# --------------------------------------------------------------------------- review findings (regressions)

RT0 = 1767225600.0


def big_cfg(*names: str, participation: float = 0.5, latency_ms: float = 50.0, max_order: float = 1e6,
            usdt: float = 1_000_000.0, btc: float = 10.0) -> BotConfig:
    inst = InstrumentConfig(SYM, "BTCUSDT", tick_size=0.01, lot_size=0.00001, min_notional=5.0)
    return BotConfig(
        venues=tuple(VenueConfig(n, n, taker_fee_bps=10.0, latency_ms=latency_ms, instruments=(inst,),
                                 starting_balances={"USDT": usdt, "BTC": btc}) for n in names),
        signal=SignalConfig(participation=participation),
        risk=RiskConfig(max_order_notional=max_order, max_net_exposure_notional=max(1e7, max_order),
                        min_top_depth_notional=0.0),
    )


def bq(venue: str, t: float, bid: float, ask: float, seq: int | None = None, *, bid_size: float = 1.0,
       ask_size: float = 1.0) -> Quote:
    return Quote(venue, SYM, bid, bid_size, ask, ask_size, RT0 + t, seq=seq)


def executions(path: Path) -> list[dict]:
    return [r for r in (json.loads(x) for x in path.read_text().splitlines()) if r["kind"] == "execution"]


def test_fills_never_take_more_than_a_quotes_displayed_size_across_signals() -> None:
    """A's only quote shows 1.0 BTC: three arbs buying on A must not buy 1.5 BTC from it."""
    cfg = big_cfg("A", "B", "C")
    quotes = [bq("A", 0.0, 49700.0, 49750.0, 1), bq("B", 0.001, 50000.0, 50010.0, 1),
              bq("C", 0.2, 50000.0, 50010.0, 1), bq("B", 1.1, 50000.0, 50010.0, 2)]
    r = run_backtest(cfg, quotes)
    bought_on_a = r.final_portfolio["A"]["BTC"] - 10.0
    assert bought_on_a == pytest.approx(1.0, abs=1e-12)  # the displayed size, not 1.5
    assert r.trades == 3 and r.outcomes == {"completed": 2, "flattened": 1}
    assert_reconciles(r, cfg)


def test_hedge_does_not_fill_into_the_bid_the_leg_just_used_up(tmp_path: Path) -> None:
    """B's bid shows 0.5 when the sell leg arrives; the hedge on B must not sell another 0.5 into it."""
    cfg = big_cfg("A", "B", participation=1.0)
    quotes = [bq("A", 0.0, 49700.0, 49750.0, 1), bq("B", 0.001, 50000.0, 50010.0, 1),
              bq("B", 0.010, 50000.0, 50010.0, 2, bid_size=0.5), bq("B", 3.0, 49000.0, 50010.0, 3, bid_size=0.5)]
    path = tmp_path / "j.jsonl"
    journal = Journal(path)
    r = run_backtest(cfg, quotes, journal=journal)
    journal.close()
    (rep,) = executions(path)
    assert [(o["venue"], o["side"], o["filled_qty"]) for o in rep["orders"]] == [
        ("A", "buy", 1.0), ("B", "sell", 0.5), ("B", "sell", 0.0), ("A", "sell", 0.5),  # hedge misses, unwind
    ]
    assert 10.0 - r.final_portfolio["B"]["BTC"] == pytest.approx(0.5, abs=1e-12)
    assert rep["outcome"] == "flattened"
    assert_reconciles(r, cfg)


def test_sub_min_notional_excess_is_dust_and_never_sent(tmp_path: Path) -> None:
    """The sell leg fills 0.02008 of 0.0201: the 0.00002 BTC (~$1) excess is below both venues' $5 minimum.

    A real venue rejects such a hedge or unwind, so none is sent and the paper venue would refuse it too.
    The arb is FLATTENED with a known dust residual instead of RESIDUAL + kill switch.
    """
    cfg = big_cfg("A", "B", participation=1.0, max_order=1000.0, usdt=100_000.0, btc=1.0)
    quotes = [bq("A", 0.0, 49700.0, 49750.0, 1), bq("B", 0.001, 50000.0, 50010.0, 1),
              bq("B", 0.020, 50000.0, 50010.0, 2, bid_size=0.02008), bq("B", 5.0, 50000.0, 50010.0, 3)]
    path = tmp_path / "j.jsonl"
    journal = Journal(path)
    r = run_backtest(cfg, quotes, journal=journal)
    journal.close()
    (rep,) = executions(path)
    assert [o["filled_qty"] for o in rep["orders"]] == [0.0201, 0.02008]  # no third order
    assert rep["outcome"] == "flattened" and rep["residual_qty"] == pytest.approx(0.00002)
    assert any("below the B min notional" in n for n in rep["notes"])
    assert not r.halted and r.residual_inventory == {"BTC": pytest.approx(0.00002)}
    assert_reconciles(r, cfg)


def test_example_config_sub_lot_residual_is_dust_and_trading_continues() -> None:
    """Binance BTC lot 1e-5, Bybit 1e-6 (config.example.toml): 7e-6 BTC no order can flatten is not a halt."""
    from arbbot.config import load_config

    cfg = load_config(Path(__file__).resolve().parents[1] / "config.example.toml")
    b, y, t0 = "binance", "bybit", 1_800_000_000.0
    quotes = [Quote(b, SYM, 79990.0, 1.0, 80000.0, 1.0, t0), Quote(y, SYM, 80240.0, 1.0, 80250.0, 1.0, t0 + 0.001),
              Quote(y, SYM, 80240.0, 0.0031234, 80250.0, 1.0, t0 + 0.040),
              Quote(y, SYM, 80100.0, 1.0, 80110.0, 1.0, t0 + 0.080), Quote(b, SYM, 79990.0, 1.0, 80000.0, 1.0, t0 + 1),
              Quote(y, SYM, 80100.0, 1.0, 80110.0, 1.0, t0 + 6), Quote(b, SYM, 79990.0, 1.0, 80000.0, 1.0, t0 + 10),
              Quote(y, SYM, 80240.0, 1.0, 80250.0, 1.0, t0 + 10.001)]
    r = run_backtest(cfg, quotes)
    assert not r.halted and r.rejections == {}
    assert r.outcomes == {"flattened": 1, "completed": 1}  # the later arb still trades
    assert r.residual_inventory == {"BTC": pytest.approx(7e-06, abs=1e-12)}
    assert_reconciles(r, cfg)


def test_hedge_is_priced_from_the_quote_received_before_it_was_sent(tmp_path: Path) -> None:
    """A's dislocation is gone at t=0.031; the hedge sent at t=0.051 must use that quote, not t=0.001's."""
    cfg = big_cfg("A", "B")
    cfg = dataclasses.replace(cfg, risk=RiskConfig(min_top_depth_notional=0.0))
    quotes = [bq("B", 0.0, 50000.0, 50010.0, 1), bq("A", 0.001, 49700.0, 49750.0, 1),
              bq("A", 0.031, 49990.0, 50000.0, 2), bq("A", 2.0, 49990.0, 50000.0, 3), bq("B", 2.0, 50000.0, 50010.0, 2)]
    path = tmp_path / "j.jsonl"
    journal = Journal(path)
    run_backtest(cfg, quotes, journal=journal)
    journal.close()
    (rep,) = executions(path)
    # floor(50000 * 1.0005) = 50025, inside the band 49995 * 1.005; not 49750 * 1.0005 = 49774.87 from t=0.001
    assert rep["notes"][0] == "hedge buy 0.01005 on A @<= 50025: filled 0.01005"
    assert rep["outcome"] == "flattened" and len(rep["orders"]) == 3


def test_signal_received_while_its_symbol_executes_is_in_flight_like_live() -> None:
    cfg = dataclasses.replace(big_cfg("A", "B", "C"), risk=RiskConfig(min_top_depth_notional=0.0))
    quotes = [bq("A", 0.0, 49700.0, 49750.0, 1), bq("B", 0.001, 50000.0, 50010.0, 1),
              bq("C", 0.020, 50000.0, 50010.0, 1)]  # received at 0.020; the first arb runs until 0.051
    r = run_backtest(cfg, quotes)
    assert (r.signals, r.approved) == (2, 1)
    assert r.rejections == {"in_flight": 1} and r.outcomes == {"completed": 1}


def lag_gap_cfg(max_hold_s: float = 30.0, lot: float = 0.001) -> BotConfig:
    ri = InstrumentConfig("X-USDT", "XUSDT", tick_size=0.01, lot_size=lot, min_notional=1.0)
    ti = InstrumentConfig("X-USD", "X/USD", tick_size=0.01, lot_size=lot, min_notional=1.0)
    return BotConfig(
        venues=(VenueConfig("ref", "binance", taker_fee_bps=0.0, slippage_bps=0.0, latency_ms=0.0,
                            instruments=(ri,), starting_balances={"USDT": 1000.0}),
                VenueConfig("tgt", "kraken", taker_fee_bps=0.0, slippage_bps=0.0, latency_ms=0.0,
                            instruments=(ti,), starting_balances={"USD": 1000.0})),
        risk=RiskConfig(min_top_depth_notional=0.0),
        reference_lag=ReferenceLagConfig(
            enabled=True, reference_venue="ref", reference_symbol="X-USDT", target_venue="tgt",
            target_symbol="X-USD", min_basis_samples=1, entry_threshold_bps=0.0, take_profit_fraction=1.0,
            stop_bps=500.0, max_hold_s=max_hold_s,
        ),
    )


def xq(venue: str, t: float, bid: float, ask: float, *, bid_size: float = 100.0, ask_size: float = 100.0) -> Quote:
    return Quote(venue, "X-USDT" if venue == "ref" else "X-USD", bid, bid_size, ask, ask_size, RT0 + t)


def test_time_stop_fires_on_time_across_a_gap_in_the_data(tmp_path: Path) -> None:
    """max_hold 30 s; every venue is silent from t=3.6 to t=300. The live bot's tick exits at t=31.

    Opened t=1.0: BUY 5.018 @ 99.63 (size 500 / 99.63 floored). The time stop at t=31.0 sells into the
    standing bid 99.60: realized 5.018 * (99.60 - 99.63) = -0.15054, not -8.28 at the post-gap 97.98.
    """
    cfg = lag_gap_cfg()
    quotes = [xq("ref", 0.0, 99.99, 100.01), xq("tgt", 1.0, 99.62, 99.63), xq("ref", 1.0, 100.99, 101.01),
              xq("tgt", 3.55, 99.60, 99.63), xq("ref", 3.6, 100.99, 101.01),
              xq("tgt", 300.05, 97.98, 98.00), xq("ref", 300.06, 98.0, 98.02)]
    path = tmp_path / "j.jsonl"
    journal = Journal(path)
    r = run_backtest(cfg, quotes, journal=journal)
    journal.close()
    opened, closed = executions(path)
    assert opened["outcome"] == "opened" and opened["finished_ts"] == pytest.approx(RT0 + 1.0)
    assert closed["outcome"] == "closed"
    assert closed["notes"] == ["closed (time) 5.018 @ 99.6", "exit priced from a stale quote (age 27.450s)"]
    assert closed["finished_ts"] == pytest.approx(RT0 + 31.0)
    assert closed["realized_pnl"] == pytest.approx(5.018 * (99.60 - 99.63), abs=1e-9)
    assert r.net_pnl == pytest.approx(-0.15054, abs=1e-9)
    assert_reconciles(r, cfg)


def test_partial_exits_of_one_position_do_not_trip_the_hedge_failure_kill_switch() -> None:
    """A position closed in 4 IOCs on a thin bid (1.5 a quote) is 3 partial exits, not 3 failed hedges."""
    cfg = dataclasses.replace(lag_gap_cfg(max_hold_s=1.0, lot=0.01),
                              risk=RiskConfig(min_top_depth_notional=0.0, max_consecutive_hedge_failures=3))
    quotes = [xq("ref", 0.0, 99.99, 100.01), xq("tgt", 0.01, 99.99, 100.01, ask_size=10.0),
              xq("ref", 0.02, 100.99, 101.01),  # BUY tgt 4.99 @ 100.01 (500 / 100.01 floored)
              xq("ref", 0.30, 99.99, 100.01),  # the reference is back: no more signals
              xq("tgt", 0.50, 99.99, 100.01, bid_size=1.5),  # thin bid; the time stop is due at t=1.02
              xq("tgt", 1.10, 99.99, 100.01, bid_size=1.5), xq("tgt", 1.20, 99.99, 100.01, bid_size=1.5),
              xq("tgt", 1.30, 99.99, 100.01, bid_size=1.5), xq("tgt", 1.40, 99.99, 100.01, bid_size=1.5)]
    r = run_backtest(cfg, quotes)
    assert r.outcomes == {"opened": 1, "flattened": 3, "closed": 1}
    assert not r.halted and r.halt_reason is None
    assert r.open_positions == 0 and r.residual_inventory == {}
    assert_reconciles(r, cfg)


def test_a_sequence_reset_inside_the_recording_is_resynced_not_dropped() -> None:
    """A reconnect (or two appended recordings) restarts the venue's seq; live, the feed resyncs the book."""
    cfg = kill_switch_cfg()
    quotes = [Quote("A", SYM, 99.99, 5.0, 100.00, 5.0, T0, seq=50), Quote("B", SYM, 99.99, 5.0, 100.00, 5.0,
                                                                          T0 + 0.001, seq=7),
              Quote("A", SYM, 99.50, 5.0, 99.51, 5.0, T0 + 1.0, seq=1),  # new connection: A is 48 bps cheap
              Quote("A", SYM, 99.40, 5.0, 99.45, 5.0, T0 + 1.5, seq=1)]  # same seq, other prices: out of order
    r = run_backtest(cfg, quotes)
    assert r.seq_resets == 1
    assert r.signals == 1 and r.approved == 1  # the post-reset quote reached the scanner
    assert r.dropped_quotes == 1
    text = r.format_report()
    assert "1 dropped (out of order or invalid)" in text and "1 sequence resets (resynced)" in text


def test_two_runs_in_one_process_write_identical_journals(tmp_path: Path) -> None:
    cfg = arb_cfg()
    quotes = synth(dislocation_rate=0.03, seed=3, duration_s=120.0)
    paths = []
    for i in range(2):
        path = tmp_path / f"run{i}.jsonl"
        journal = Journal(path)
        assert run_backtest(cfg, quotes, journal=journal).trades > 0
        journal.close()
        paths.append(path)
    assert paths[0].read_bytes() == paths[1].read_bytes()
    first_signal = next(r for r in (json.loads(x) for x in paths[1].read_text().splitlines()) if r["kind"] == "signal")
    assert first_signal["signal"]["id"] == "sig-1"


def test_a_position_left_with_unsellable_dust_is_closed_and_still_reconciles() -> None:
    """The time-stop exit fills 5.010 of 5.018: 0.008 X (~$0.80) is below the $1 minimum, so no order can
    ever sell it. The position is closed as dust (no RESIDUAL, no kill switch) and the dust is carried."""
    cfg = lag_gap_cfg(max_hold_s=1.0)
    quotes = [xq("ref", 0.0, 99.99, 100.01), xq("tgt", 1.0, 99.62, 99.63), xq("ref", 1.0, 100.99, 101.01),
              xq("ref", 1.5, 99.99, 100.01), xq("tgt", 1.9, 99.60, 99.63, bid_size=5.01),
              xq("tgt", 3.0, 99.60, 99.63)]
    r = run_backtest(cfg, quotes)
    assert r.outcomes == {"opened": 1, "closed": 1}
    assert not r.halted and r.open_positions == 0
    assert r.residual_inventory == {"X": pytest.approx(0.008, abs=1e-12)}
    assert (r.trades, r.closed_trades) == (1, 1)
    assert_reconciles(r, cfg)
