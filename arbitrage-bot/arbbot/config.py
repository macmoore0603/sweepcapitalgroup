"""Typed, validated configuration loaded from TOML.

Every number that decides whether money moves lives here, not in code, so it
can be tuned in the backtest and reviewed in one place. ``load_config`` fails
loudly on anything inconsistent rather than trading on a half-valid config.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

_SYMBOL_RE = re.compile(r"^[A-Z0-9]+-[A-Z0-9]+$")
MODES = ("paper", "live")
# Quote currencies the bot can account in. Every money figure (risk limits, depth
# floor, PnL, marks) is in a symbol's quote currency and is summed across symbols
# at par, so only USD and USD stablecoins are accepted: a BTC- or EUR-quoted
# symbol would make max_order_notional = 500 mean 500 BTC (or EUR).
USD_LIKE_QUOTES = ("USD", "USDT", "USDC", "FDUSD", "TUSD", "USDP", "DAI")
DEFAULT_JOURNAL_PATH = "logs/journal.jsonl"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class InstrumentConfig:
    symbol: str  # canonical BASE-QUOTE, e.g. "BTC-USDT"
    venue_symbol: str  # the venue's spelling: "BTCUSDT", "BTC/USD", "BTC-USD"
    tick_size: float = 0.01
    lot_size: float = 0.00001
    min_notional: float = 5.0  # quote ccy; the venue rejects smaller orders


@dataclass(frozen=True, slots=True)
class VenueConfig:
    name: str
    feed: str  # adapter key: binance | bybit | kraken | coinbase | okx
    taker_fee_bps: float  # check your actual account tier; this decides profitability
    maker_fee_bps: float = 0.0
    slippage_bps: float = 1.0  # expected adverse fill vs quote, per leg
    latency_ms: float = 50.0  # order round trip; paper/backtest fills see the book this much later
    instruments: tuple[InstrumentConfig, ...] = ()
    starting_balances: dict[str, float] = field(default_factory=dict)  # paper mode inventory

    def instrument(self, symbol: str) -> InstrumentConfig | None:
        for inst in self.instruments:
            if inst.symbol == symbol:
                return inst
        return None


@dataclass(frozen=True, slots=True)
class SignalConfig:
    min_net_edge_bps: float = 5.0  # X: required edge AFTER fees + slippage on both legs
    participation: float = 0.5  # take at most this fraction of the displayed top size
    persistence_ms: float = 0.0  # edge must persist this long before firing (0 = fire at once)
    cooldown_ms: float = 1000.0  # per venue pair, after a trade, before re-firing


@dataclass(frozen=True, slots=True)
class ReferenceLagConfig:
    enabled: bool = False
    reference_venue: str = "binance"
    reference_symbol: str = "BTC-USDT"
    target_venue: str = ""
    target_symbol: str = ""
    basis_halflife_s: float = 300.0  # EMA half-life of the normal target-vs-reference premium
    min_basis_samples: int = 100  # warm-up: no signals before; then the basis is seeded with their median
    entry_threshold_bps: float = 10.0  # edge to the take-profit target (tp * gap to fair) AFTER round-trip costs
    take_profit_fraction: float = 0.8  # target = entry + this fraction of the gap to fair
    stop_bps: float = 15.0  # hard stop distance from entry
    max_hold_s: float = 30.0  # time stop


@dataclass(frozen=True, slots=True)
class RiskConfig:
    max_order_notional: float = 500.0  # per trade, quote ccy
    max_net_exposure_notional: float = 1000.0  # |net base across venues| * mid, incl. open positions
    max_open_positions: int = 1  # REFERENCE_LAG positions
    min_top_depth_notional: float = 2000.0  # liquidity floor per venue/symbol
    liquidity_recovery_s: float = 5.0  # depth must stay above the floor this long to re-enable
    max_quote_age_ms: float = 1500.0  # older quotes are stale: no trading on them
    daily_loss_limit: float = 50.0  # realized loss (UTC day) that trips the kill switch
    max_consecutive_hedge_failures: int = 3  # unequal-fill cross-venue arbs in a row that trip the kill switch
    max_trades_per_minute: int = 20


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    leg_timeout_ms: float = 2000.0  # per order; on timeout the order is reconciled via query
    max_slippage_bps: float = 5.0  # entry limit = quote +/- this
    hedge_retry: bool = True  # on unequal fills, first try to complete the hedge leg
    unwind_slippage_bps: float = 50.0  # hedge/unwind/stop exits may cross this far to get flat


@dataclass(frozen=True, slots=True)
class BotConfig:
    mode: str = "paper"
    venues: tuple[VenueConfig, ...] = ()
    signal: SignalConfig = SignalConfig()
    reference_lag: ReferenceLagConfig = ReferenceLagConfig()
    risk: RiskConfig = RiskConfig()
    execution: ExecutionConfig = ExecutionConfig()
    journal_path: str = DEFAULT_JOURNAL_PATH

    def venue(self, name: str) -> VenueConfig:
        for v in self.venues:
            if v.name == name:
                return v
        raise KeyError(f"unknown venue {name!r}")

    def venues_for(self, symbol: str) -> tuple[VenueConfig, ...]:
        return tuple(v for v in self.venues if v.instrument(symbol) is not None)

    def symbols(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for v in self.venues:
            for inst in v.instruments:
                seen.setdefault(inst.symbol, None)
        return tuple(seen)

    def cross_venue_symbols(self) -> tuple[str, ...]:
        """Symbols listed on at least two venues (the only ones a cross-venue arb can trade)."""
        return tuple(s for s in self.symbols() if len(self.venues_for(s)) >= 2)


def _build(cls: type, raw: dict[str, Any], where: str) -> Any:
    known = {f.name for f in fields(cls)}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"{where}: unknown keys {sorted(unknown)}")
    try:
        return cls(**raw)
    except TypeError as e:
        raise ConfigError(f"{where}: {e}") from None


def parse_config(raw: dict[str, Any]) -> BotConfig:
    raw = dict(raw)
    venues = []
    for i, v in enumerate(raw.pop("venues", [])):
        v = dict(v)
        where = f"venues[{i}]"
        insts = tuple(
            _build(InstrumentConfig, dict(x), f"{where}.instruments[{j}]")
            for j, x in enumerate(v.pop("instruments", []))
        )
        balances = {str(k): float(x) for k, x in v.pop("starting_balances", {}).items()}
        venues.append(_build(VenueConfig, {**v, "instruments": insts, "starting_balances": balances}, where))
    cfg = BotConfig(
        mode=raw.pop("mode", "paper"),
        journal_path=raw.pop("journal_path", DEFAULT_JOURNAL_PATH),  # not BotConfig.journal_path: a slot descriptor
        venues=tuple(venues),
        signal=_build(SignalConfig, raw.pop("signal", {}), "signal"),
        reference_lag=_build(ReferenceLagConfig, raw.pop("reference_lag", {}), "reference_lag"),
        risk=_build(RiskConfig, raw.pop("risk", {}), "risk"),
        execution=_build(ExecutionConfig, raw.pop("execution", {}), "execution"),
    )
    if raw:
        raise ConfigError(f"unknown top-level keys {sorted(raw)}")
    validate(cfg)
    return cfg


def load_config(path: str | Path) -> BotConfig:
    with open(path, "rb") as fh:
        return parse_config(tomllib.load(fh))


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ConfigError(msg)


def validate(cfg: BotConfig) -> None:
    _require(cfg.mode in MODES, f"mode must be one of {MODES}, got {cfg.mode!r}")
    _require(isinstance(cfg.journal_path, str) and bool(cfg.journal_path), "journal_path must be a non-empty string")
    _require(len(cfg.venues) >= 1, "at least one venue is required")
    names = [v.name for v in cfg.venues]
    _require(len(names) == len(set(names)), f"duplicate venue names: {names}")
    for v in cfg.venues:
        w = f"venue {v.name!r}"
        _require(bool(v.name) and bool(v.feed), f"{w}: name and feed are required")
        _require(v.taker_fee_bps >= 0 and v.maker_fee_bps >= -10, f"{w}: fees out of range")
        _require(v.slippage_bps >= 0, f"{w}: slippage_bps must be >= 0")
        _require(v.latency_ms >= 0, f"{w}: latency_ms must be >= 0")
        _require(len(v.instruments) >= 1, f"{w}: at least one instrument is required")
        seen = set()
        for inst in v.instruments:
            _require(bool(_SYMBOL_RE.match(inst.symbol)), f"{w}: symbol {inst.symbol!r} must be BASE-QUOTE")
            quote = inst.symbol.partition("-")[2]
            _require(quote in USD_LIKE_QUOTES,
                     f"{w}: {inst.symbol} is quoted in {quote}; risk limits, PnL and marks are in USD-like quote "
                     f"currencies valued at par, so the quote currency must be one of {', '.join(USD_LIKE_QUOTES)}")
            _require(inst.symbol not in seen, f"{w}: duplicate instrument {inst.symbol}")
            seen.add(inst.symbol)
            _require(bool(inst.venue_symbol), f"{w}: {inst.symbol} needs venue_symbol")
            _require(inst.tick_size > 0 and inst.lot_size > 0, f"{w}: {inst.symbol} tick/lot must be > 0")
            _require(inst.min_notional >= 0, f"{w}: {inst.symbol} min_notional must be >= 0")
    s = cfg.signal
    _require(s.min_net_edge_bps >= 0, "signal.min_net_edge_bps must be >= 0 (never trade below cost)")
    _require(0 < s.participation <= 1, "signal.participation must be in (0, 1]")
    _require(s.persistence_ms >= 0 and s.cooldown_ms >= 0, "signal timers must be >= 0")
    r = cfg.risk
    for name in ("max_order_notional", "max_net_exposure_notional", "max_quote_age_ms", "daily_loss_limit"):
        _require(getattr(r, name) > 0, f"risk.{name} must be > 0")
    _require(r.max_order_notional <= r.max_net_exposure_notional,
             "risk.max_order_notional must be <= max_net_exposure_notional (a failed hedge leaves one full leg)")
    _require(r.min_top_depth_notional >= 0 and r.liquidity_recovery_s >= 0, "risk liquidity settings must be >= 0")
    _require(r.max_open_positions >= 0 and r.max_trades_per_minute >= 1, "risk counters out of range")
    _require(r.max_consecutive_hedge_failures >= 1, "risk.max_consecutive_hedge_failures must be >= 1")
    e = cfg.execution
    _require(e.leg_timeout_ms > 0, "execution.leg_timeout_ms must be > 0")
    _require(e.max_slippage_bps >= 0 and e.unwind_slippage_bps >= e.max_slippage_bps,
             "execution.unwind_slippage_bps must be >= max_slippage_bps >= 0")
    lag = cfg.reference_lag
    if lag.enabled:
        ref = next((v for v in cfg.venues if v.name == lag.reference_venue), None)
        tgt = next((v for v in cfg.venues if v.name == lag.target_venue), None)
        _require(ref is not None and ref.instrument(lag.reference_symbol) is not None,
                 "reference_lag: reference venue/symbol not configured")
        _require(tgt is not None and tgt.instrument(lag.target_symbol) is not None,
                 "reference_lag: target venue/symbol not configured")
        _require(lag.reference_venue != lag.target_venue, "reference_lag: target must differ from reference")
        _require(lag.basis_halflife_s > 0 and lag.min_basis_samples >= 1, "reference_lag: basis settings")
        _require(lag.entry_threshold_bps >= 0 and lag.stop_bps > 0 and lag.max_hold_s > 0,
                 "reference_lag: thresholds must be positive")
        _require(0 < lag.take_profit_fraction <= 1, "reference_lag.take_profit_fraction must be in (0, 1]")
    else:
        _require(len(cfg.cross_venue_symbols()) >= 1,
                 "no symbol is listed on two venues: nothing to arbitrage (or enable reference_lag)")
