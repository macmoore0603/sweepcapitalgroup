"""Tests for arbbot.cli: synth -> backtest end to end, the example config, live gating, scan/paper/record.

Long-running commands get fake feeds (``build_feeds`` is patched) so nothing
touches the network; live trading is only ever exercised up to its gate.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
import sys
import tomllib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from arbbot import cli
from arbbot.clock import Clock
from arbbot.config import BotConfig, load_config, parse_config
from arbbot.execution.binance_live import MAINNET_URL, TESTNET_URL, BinanceSpotClient
from arbbot.feeds.replay import load_quotes
from arbbot.feeds.venues import ADAPTERS
from arbbot.models import FeedEvent, FeedStatus, Quote

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "config.example.toml"
REAL_BUILD_FEEDS = cli.build_feeds
LIVE_ENV = {
    cli.LIVE_CONFIRM_ENV: cli.LIVE_CONFIRM_VALUE,
    cli.BINANCE_KEY_ENV: "test-key-0000",
    cli.BINANCE_SECRET_ENV: "test-secret-0000",
}


def write_config(path: Path, *, mode: str = "paper", venues: tuple[tuple[str, str], ...] = (
        ("binance", "binance"), ("bybit", "bybit")), journal: Path | None = None) -> Path:
    blocks = [f'mode = "{mode}"', f'journal_path = "{(journal or path.with_suffix(".jsonl")).as_posix()}"']
    for name, feed in venues:
        blocks.append(f"""
[[venues]]
name = "{name}"
feed = "{feed}"
taker_fee_bps = 10.0
slippage_bps = 0.0
latency_ms = 1.0

[[venues.instruments]]
symbol = "BTC-USDT"
venue_symbol = "BTCUSDT"
tick_size = 0.01
lot_size = 0.00001
min_notional = 5.0

[venues.starting_balances]
USDT = 10000.0
BTC = 0.1
""")
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run in a temp dir (default journal paths land there) and never open a real websocket."""
    monkeypatch.chdir(tmp_path)

    def no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("a test tried to start real market-data feeds")

    monkeypatch.setattr(cli, "build_feeds", no_network)


# --------------------------------------------------------------------------- synth -> backtest


def test_synth_then_backtest_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = tmp_path / "synth.jsonl"
    assert cli.main(["synth", "-c", str(EXAMPLE), "--out", str(data), "--duration", "300"], env={}) == 0
    first = data.read_bytes()
    assert cli.main(["synth", "-c", str(EXAMPLE), "--out", str(data), "--duration", "300"], env={}) == 0
    assert data.read_bytes() == first  # deterministic and overwritten, not appended
    quotes = load_quotes(data)
    assert len(quotes) == 2 * 300 * 10
    assert {q.venue for q in quotes} == {"binance", "bybit"} and {q.symbol for q in quotes} == {"BTC-USDT"}

    report = tmp_path / "out" / "report.json"
    journal = tmp_path / "journal.jsonl"
    capsys.readouterr()
    rc = cli.main(["backtest", "-c", str(EXAMPLE), "--data", str(data), "--report", str(report),
                   "--journal", str(journal)], env={})
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("Backtest\n") and "reconciliation error" in out and f"report written to {report}" in out
    result = json.loads(report.read_text())
    assert result["events"] == 6000 and result["trades"] > 0
    assert result["net_pnl"] > 0 and abs(result["reconciliation_error"]) < 1e-6
    assert result["equity_curve"][-1][2] == pytest.approx(result["final_equity"] - result["initial_equity"])
    recs = [json.loads(line) for line in journal.read_text().splitlines()]
    kinds = [r["kind"] for r in recs]
    assert kinds[0] == "start" and kinds[-1] == "shutdown"  # each run is bracketed
    assert set(kinds[1:-1]) == {"signal", "risk", "execution"}
    assert recs[0]["mode"] == "backtest" and recs[0]["data"] == str(data) and recs[0]["config"] == str(EXAMPLE)


def test_synth_with_explicit_venues_needs_no_config(tmp_path: Path) -> None:
    out = tmp_path / "s.jsonl"
    rc = cli.main(["synth", "-c", str(tmp_path / "missing.toml"), "--out", str(out), "--symbol", "ETH-USDT",
                   "--venues", "x,y,z", "--duration", "2", "--hz", "5", "--base-price", "3000"], env={})
    assert rc == 0
    quotes = load_quotes(out)
    assert len(quotes) == 30 and {q.venue for q in quotes} == {"x", "y", "z"}


# --------------------------------------------------------------------------- example config


def test_example_config_loads_with_real_venue_values() -> None:
    cfg = load_config(EXAMPLE)
    assert cfg.mode == "paper" and not cfg.reference_lag.enabled
    assert [v.name for v in cfg.venues] == ["binance", "bybit", "kraken", "coinbase"]
    assert all(v.feed in ADAPTERS for v in cfg.venues)
    assert cfg.cross_venue_symbols() == ("BTC-USDT", "ETH-USDT", "BTC-USD")
    assert [v.name for v in cfg.venues_for("BTC-USD")] == ["kraken", "coinbase"]  # never paired with USDT
    fees = {v.name: v.taker_fee_bps for v in cfg.venues}
    assert fees == {"binance": 10.0, "bybit": 10.0, "kraken": 80.0, "coinbase": 120.0}
    b = cfg.venue("binance").instrument("BTC-USDT")
    assert b is not None and (b.venue_symbol, b.tick_size, b.lot_size, b.min_notional) == ("BTCUSDT", 0.01, 0.00001, 5.0)
    y = cfg.venue("bybit").instrument("BTC-USDT")
    assert y is not None and (y.tick_size, y.lot_size) == (0.1, 0.000001)
    k = cfg.venue("kraken").instrument("BTC-USD")
    assert k is not None and k.venue_symbol == "BTC/USD"
    # Paper inventory on both sides of every listed symbol, so both directions can trade.
    for v in cfg.venues:
        for i in v.instruments:
            base, quote = i.symbol.split("-")
            assert v.starting_balances.get(base, 0) > 0 and v.starting_balances.get(quote, 0) > 0


def test_journal_path_defaults_to_a_string_when_omitted() -> None:
    """Regression: a slots dataclass's class attribute is a slot descriptor, not the default value."""
    text = EXAMPLE.read_text(encoding="utf-8").replace('journal_path = "logs/journal.jsonl"', "")
    cfg = parse_config(tomllib.loads(text))
    assert cfg.journal_path == "logs/journal.jsonl"
    with pytest.raises(ValueError, match="journal_path"):
        parse_config({**tomllib.loads(text), "journal_path": 3})


def test_example_reference_lag_block_is_valid_when_uncommented() -> None:
    text = EXAMPLE.read_text(encoding="utf-8")
    head, sep, tail = text.partition("# [reference_lag]")
    assert sep
    uncommented = "[reference_lag]\n" + "\n".join(line.removeprefix("# ") for line in tail.splitlines())
    cfg = parse_config(tomllib.loads(head + uncommented))
    lag = cfg.reference_lag
    assert lag.enabled and (lag.reference_venue, lag.reference_symbol) == ("binance", "BTC-USDT")
    assert (lag.target_venue, lag.target_symbol) == ("kraken", "BTC-USD")


# --------------------------------------------------------------------------- live gating


def test_live_refuses_the_example_config(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["live", "-c", str(EXAMPLE)], env={}) == cli.EXIT_USAGE
    err = capsys.readouterr().err
    assert "live trading refused" in err
    assert 'config mode is "paper"' in err
    assert f"{cli.LIVE_CONFIRM_ENV}={cli.LIVE_CONFIRM_VALUE}" in err
    assert "bybit (feed bybit), kraken (feed kraken), coinbase (feed coinbase)" in err
    assert "only Binance spot" in err
    assert cli.BINANCE_KEY_ENV in err and cli.BINANCE_SECRET_ENV in err


def binance_only(tmp_path: Path, mode: str = "live") -> Path:
    return write_config(tmp_path / "live.toml", mode=mode,
                        venues=(("binance", "binance"), ("binance_b", "binance")))


@pytest.mark.parametrize("missing, expect", [
    (cli.LIVE_CONFIRM_ENV, "I_ACCEPT_THE_RISK"),
    (cli.BINANCE_KEY_ENV, "credentials missing: set ARBBOT_BINANCE_API_KEY"),
    (cli.BINANCE_SECRET_ENV, "credentials missing: set ARBBOT_BINANCE_API_SECRET"),
])
def test_live_refuses_without_each_gate(tmp_path: Path, capsys: pytest.CaptureFixture[str], missing: str,
                                        expect: str) -> None:
    env = {k: v for k, v in LIVE_ENV.items() if k != missing}
    assert cli.main(["live", "-c", str(binance_only(tmp_path))], env=env) == cli.EXIT_USAGE
    err = capsys.readouterr().err
    assert expect in err and err.count("\n  - ") == 1  # exactly one problem reported


def test_live_refuses_wrong_confirmation_and_paper_mode(tmp_path: Path) -> None:
    env = {**LIVE_ENV, cli.LIVE_CONFIRM_ENV: "yes"}
    assert len(cli.live_problems(load_config(binance_only(tmp_path)), env)) == 1
    problems = cli.live_problems(load_config(binance_only(tmp_path, mode="paper")), LIVE_ENV)
    assert problems == ['config mode is "paper": set mode = "live" in the config to trade real orders']


def test_live_gate_passes_and_builds_testnet_clients_unless_mainnet(tmp_path: Path) -> None:
    cfg = load_config(binance_only(tmp_path))
    assert cli.live_problems(cfg, LIVE_ENV) == []
    clients = cli.build_live_clients(cfg, LIVE_ENV, mainnet=False)
    assert set(clients) == {"binance", "binance_b"}
    for c in clients.values():
        assert isinstance(c, BinanceSpotClient) and c.is_testnet and c.base_url == TESTNET_URL
        assert "test-secret" not in repr(c)
    main = cli.build_live_clients(cfg, LIVE_ENV, mainnet=True)
    assert all(not c.is_testnet and c.base_url == MAINNET_URL for c in main.values())  # type: ignore[attr-defined]


def test_testnet_live_mode_reads_testnet_market_data(tmp_path: Path) -> None:
    cfg = load_config(binance_only(tmp_path))
    feeds = REAL_BUILD_FEEDS(cfg, cli.WallClock(), binance_ws=cli.BINANCE_TESTNET_WS)  # builds, never connects
    assert [f.url for f in feeds] == ["wss://stream.testnet.binance.vision/stream?streams=btcusdt@bookTicker"] * 2
    default = REAL_BUILD_FEEDS(cfg, cli.WallClock())
    assert default[0].url == "wss://data-stream.binance.vision/stream?streams=btcusdt@bookTicker"


# --------------------------------------------------------------------------- usage errors


def test_usage_errors_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                            monkeypatch: pytest.MonkeyPatch) -> None:
    assert cli.main([], env={}) == 2
    assert cli.main(["nope"], env={}) == 2
    assert cli.main(["scan", "-c", str(tmp_path / "missing.toml")], env={}) == 2
    assert "config file not found" in capsys.readouterr().err
    bad = tmp_path / "bad.toml"
    bad.write_text("mode = ", encoding="utf-8")
    assert cli.main(["backtest", "-c", str(bad), "--data", "x"], env={}) == 2
    assert "invalid TOML" in capsys.readouterr().err
    unknown = tmp_path / "unknown.toml"
    unknown.write_text("bogus = 1\n" + EXAMPLE.read_text(), encoding="utf-8")  # top level, before any table
    assert cli.main(["scan", "-c", str(unknown)], env={}) == 2
    assert "unknown top-level keys ['bogus']" in capsys.readouterr().err
    assert cli.main(["backtest", "-c", str(EXAMPLE), "--data", str(tmp_path / "none.jsonl")], env={}) == 2
    assert "data file not found" in capsys.readouterr().err
    garbage = tmp_path / "garbage.jsonl"
    garbage.write_text("{not json\n", encoding="utf-8")
    assert cli.main(["backtest", "-c", str(EXAMPLE), "--data", str(garbage)], env={}) == 2
    assert cli.main(["synth", "-c", str(EXAMPLE), "--out", str(tmp_path / "s"), "--venues", "solo",
                     "--symbol", "BTC-USDT"], env={}) == 2
    assert cli.main(["record", "-c", str(EXAMPLE), "--out", "x", "--duration", "0"], env={}) == 2
    unknown_feed = write_config(tmp_path / "feed.toml", venues=(("a", "nyse"), ("b", "binance")))
    monkeypatch.setattr(cli, "build_feeds", REAL_BUILD_FEEDS)  # it must refuse before connecting anything
    assert cli.main(["scan", "-c", str(unknown_feed)], env={}) == 2
    assert "unknown feed 'nyse'" in capsys.readouterr().err


def test_python_dash_m_entry_point() -> None:
    out = subprocess.run([sys.executable, "-m", "arbbot", "--version"], capture_output=True, text=True,
                         cwd=ROOT, timeout=60, check=False)
    assert out.returncode == 0 and out.stdout.strip() == "arbbot 0.1.0"


# --------------------------------------------------------------------------- scan / paper / record with fake feeds


class FakeFeed:
    """Streams one venue's constant quote every 20 ms, stamped with the live clock, until stopped."""

    def __init__(self, venue: str, clock: Clock, bid: float, ask: float) -> None:
        self.venue = venue
        self._clock = clock
        self._bid, self._ask = bid, ask
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def stream(self) -> AsyncIterator[FeedEvent]:
        yield FeedStatus(self.venue, True, self._clock.now())
        seq = 0
        while not self._stop.is_set():
            seq += 1
            yield Quote(self.venue, "BTC-USDT", self._bid, 50.0, self._ask, 50.0, self._clock.now(), seq=seq)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), 0.02)
        yield FeedStatus(self.venue, False, self._clock.now(), "stopped")


@pytest.fixture
def fake_feeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """binance 99.99/100.00 and bybit 100.40/100.41: buy binance, sell bybit for 40 bps gross."""
    prices = {"binance": (99.99, 100.00), "bybit": (100.40, 100.41)}

    def build(cfg: BotConfig, clock: Clock, *, binance_ws: str | None = None) -> list[FakeFeed]:
        return [FakeFeed(v.name, clock, *prices[v.name]) for v in cfg.venues]

    monkeypatch.setattr(cli, "build_feeds", build)


def journal_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_scan_command_journals_signals_and_never_executes(tmp_path: Path, fake_feeds: None,
                                                          capsys: pytest.CaptureFixture[str]) -> None:
    cfg = write_config(tmp_path / "c.toml")
    journal = tmp_path / "scan.jsonl"
    assert cli.main(["scan", "-c", str(cfg), "--duration", "0.3", "--journal", str(journal)], env={}) == 0
    recs = journal_records(journal)
    kinds = [r["kind"] for r in recs]
    assert kinds[0] == "start" and kinds[-1] == "shutdown" and "execution" not in kinds
    decisions = [r for r in recs if r["kind"] == "risk"]
    assert decisions and all(d["approved"] and d["scan_only"] for d in decisions)
    assert kinds.count("signal") == len(decisions)
    summary = json.loads(capsys.readouterr().out)
    assert summary["counters"]["executions"] == 0 and summary["counters"]["approved"] == len(decisions)


def test_paper_command_fills_against_the_live_book(tmp_path: Path, fake_feeds: None,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    cfg = write_config(tmp_path / "c.toml")
    journal = tmp_path / "paper.jsonl"
    assert cli.main(["paper", "-c", str(cfg), "--duration", "0.4", "--journal", str(journal)], env={}) == 0
    executions = [r for r in journal_records(journal) if r["kind"] == "execution"]
    # bybit holds 0.1 BTC: one arb of 0.1 sells it all, after which that direction has no size.
    assert [e["outcome"] for e in executions] == ["completed"]
    (e,) = executions
    assert [(o["venue"], o["side"], o["filled_qty"], o["avg_price"]) for o in e["orders"]] == [
        ("binance", "buy", 0.1, 100.0), ("bybit", "sell", 0.1, 100.4)]
    # 0.1 * (100.40 - 100.00) - fees (10.0 + 10.04) * 10 bps
    assert e["realized_pnl"] == pytest.approx(0.04 - 0.02004, abs=1e-9)
    summary = json.loads(capsys.readouterr().out)
    assert summary["counters"]["outcomes"] == {"completed": 1} and summary["halted"] is False


def test_record_command_writes_replayable_quotes(tmp_path: Path, fake_feeds: None) -> None:
    cfg = write_config(tmp_path / "c.toml")
    out = tmp_path / "rec.jsonl"
    assert cli.main(["record", "-c", str(cfg), "--out", str(out), "--duration", "0.3"], env={}) == 0
    quotes = load_quotes(out)
    assert len(quotes) >= 4 and {q.venue for q in quotes} == {"binance", "bybit"}
    assert cli.main(["backtest", "-c", str(cfg), "--data", str(out)], env={}) == 0


# --------------------------------------------------------------------------- review findings (regressions)


def test_credentials_from_a_secret_file_are_stripped_before_use(tmp_path: Path) -> None:
    """Kubernetes/Docker secret files end in a newline: it must not reach the X-MBX-APIKEY header."""
    cfg = load_config(binance_only(tmp_path))
    env = {**LIVE_ENV, cli.BINANCE_KEY_ENV: "test-key-0000\n", cli.BINANCE_SECRET_ENV: " test-secret-0000\r\n"}
    assert cli.live_problems(cfg, env) == []
    for c in cli.build_live_clients(cfg, env, mainnet=False).values():
        assert c._creds.api_key == "test-key-0000" and c._creds.secret == "test-secret-0000"  # type: ignore[attr-defined]


def test_credentials_with_inner_whitespace_refuse_live_without_echoing_them(tmp_path: Path,
                                                                             capsys: pytest.CaptureFixture[str]) -> None:
    env = {**LIVE_ENV, cli.BINANCE_KEY_ENV: "test-key\n0000"}
    assert cli.main(["live", "-c", str(binance_only(tmp_path))], env=env) == cli.EXIT_USAGE
    err = capsys.readouterr().err
    assert f"{cli.BINANCE_KEY_ENV} must not contain whitespace or control characters" in err
    assert "test-key" not in err


def test_backtests_appended_to_one_journal_are_bracketed_runs(tmp_path: Path) -> None:
    data = tmp_path / "synth.jsonl"
    assert cli.main(["synth", "-c", str(EXAMPLE), "--out", str(data), "--duration", "120"], env={}) == 0
    journal = tmp_path / "bt.jsonl"
    for _ in range(2):
        assert cli.main(["backtest", "-c", str(EXAMPLE), "--data", str(data), "--journal", str(journal)], env={}) == 0
    recs = [json.loads(line) for line in journal.read_text().splitlines()]
    starts = [i for i, r in enumerate(recs) if r["kind"] == "start"]
    ends = [i for i, r in enumerate(recs) if r["kind"] == "shutdown"]
    assert len(starts) == len(ends) == 2 and starts[0] == 0 and ends[-1] == len(recs) - 1
    assert starts[1] == ends[0] + 1
    runs = [recs[starts[0]:ends[0] + 1], recs[starts[1]:ends[1] + 1]]
    for run in runs:
        assert run[0]["data"] == str(data) and run[0]["config"] == str(EXAMPLE)
        ids = [r["signal"]["id"] for r in run if r["kind"] == "signal"]
        assert ids and len(ids) == len(set(ids))  # unique within a run
        risk_ids = {r["signal_id"] for r in run if r["kind"] == "risk"}
        assert risk_ids == set(ids)
    assert [r for r in runs[0] if r["kind"] != "start"] == [r for r in runs[1] if r["kind"] != "start"]


@pytest.mark.parametrize("symbol", ["ETH-BTC", "BTC-EUR", "SOL-ETH"])
def test_symbols_not_quoted_in_usd_are_refused(symbol: str) -> None:
    """Risk limits, PnL and marks are in quote currency summed at par: 500 must never mean 500 BTC."""
    raw = tomllib.loads(EXAMPLE.read_text(encoding="utf-8"))
    raw["venues"][0]["instruments"][0]["symbol"] = symbol
    with pytest.raises(ValueError, match=r"quote currency must be one of USD, USDT, USDC"):
        parse_config(raw)


def test_usd_like_quotes_are_accepted() -> None:
    raw = tomllib.loads(EXAMPLE.read_text(encoding="utf-8"))
    raw["venues"][0]["instruments"][0]["symbol"] = "BTC-USDC"
    raw["venues"][1]["instruments"][0]["symbol"] = "BTC-USDC"
    assert "BTC-USDC" in parse_config(raw).cross_venue_symbols()
