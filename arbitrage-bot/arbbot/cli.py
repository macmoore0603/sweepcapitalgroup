"""Command line: ``arbbot scan | paper | live | record | backtest | synth``.

Exit codes: 0 ok, 1 runtime failure, 2 configuration or usage error (bad
arguments, unreadable config or data file, live trading refused).

* ``scan``     live feeds; signals and risk decisions are journaled, no orders.
* ``paper``    live feeds; one ``PaperExchange`` per venue filling against the
               live QuoteBook as of each order's arrival (after its latency).
* ``live``     real orders. Refused unless the config says ``mode = "live"``,
               ``ARBBOT_LIVE_CONFIRM=I_ACCEPT_THE_RISK`` is set, every venue has
               a live order client (only Binance spot exists) and its API
               credentials are set. Binance testnet unless ``--mainnet``.
* ``record``   write live quotes to JSONL for ``backtest``.
* ``backtest`` replay a JSONL/CSV quote file with paper fills and print a report.
* ``synth``    write deterministic synthetic quotes (demos and tests only).

Feeds come from ``feeds.venues.ADAPTERS`` by each venue's ``feed`` key.
SIGINT/SIGTERM stop the long-running commands gracefully.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import re
import signal
import sys
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path

from . import __version__
from .alerts import alerter_from_env
from .app import Bot, portfolio_from_config
from .backtest import run_backtest
from .clock import Clock, WallClock
from .config import BotConfig, ConfigError, load_config
from .execution.base import ExchangeClient
from .execution.binance_live import MAINNET_URL, TESTNET_URL, BinanceSpotClient
from .execution.paper import BookAt, PaperExchange, realtime_sleep_until
from .feeds.base import QuoteBook
from .feeds.recorder import QuoteRecorder, record
from .feeds.replay import generate_synthetic, load_quotes
from .feeds.venues import ADAPTERS, BinanceAdapter, VenueAdapter, new_adapter
from .feeds.ws import WebSocketFeed
from .journal import Journal
from .portfolio import Portfolio

log = logging.getLogger("arbbot")

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2

LIVE_CONFIRM_ENV = "ARBBOT_LIVE_CONFIRM"
LIVE_CONFIRM_VALUE = "I_ACCEPT_THE_RISK"
BINANCE_KEY_ENV = "ARBBOT_BINANCE_API_KEY"
BINANCE_SECRET_ENV = "ARBBOT_BINANCE_API_SECRET"
LIVE_CLIENT_FEEDS = ("binance",)  # venues (by feed key) with a live order client
BINANCE_TESTNET_WS = "wss://stream.testnet.binance.vision"  # testnet market data matches the testnet book
SYNTH_START_TS = 1767225600.0  # 2026-01-01T00:00:00Z: fixed so synth output is reproducible
_BAD_CREDENTIAL_CHARS = re.compile(r"[\s\x00-\x1f\x7f]")


class UsageError(Exception):
    """Bad arguments or configuration: exit code 2."""


# --------------------------------------------------------------------------- building blocks


def build_feeds(cfg: BotConfig, clock: Clock, *, binance_ws: str | None = None) -> list[WebSocketFeed]:
    """One reconnecting websocket feed per venue, adapter chosen by the venue's ``feed`` key."""
    feeds = []
    for i, v in enumerate(cfg.venues):
        if v.feed not in ADAPTERS:
            raise UsageError(f"venue {v.name!r}: unknown feed {v.feed!r}; known: {sorted(ADAPTERS)}")
        adapter: VenueAdapter = new_adapter(v.feed)
        if v.feed == "binance" and binance_ws is not None:
            adapter = BinanceAdapter(base_url=binance_ws)
        feeds.append(WebSocketFeed(adapter, v, clock, seed=i))
    return feeds


def build_paper_clients(cfg: BotConfig, book: QuoteBook, clock: Clock,
                        portfolio: Portfolio | None = None) -> dict[str, ExchangeClient]:
    """A ``PaperExchange`` per venue reading the live book at each order's arrival time.

    With ``portfolio``, orders the venue's balance cannot cover are refused, as a real venue would.
    """
    sleep_until = realtime_sleep_until(clock)
    return {v.name: PaperExchange(v, _live_book(book, v.name), clock, sleep_until=sleep_until, portfolio=portfolio)
            for v in cfg.venues}


def _live_book(book: QuoteBook, venue: str) -> BookAt:
    """``book_at`` for live paper trading: called after the order's latency, so "now" is its arrival."""
    return lambda symbol, t: book.get(venue, symbol)


def live_problems(cfg: BotConfig, env: Mapping[str, str]) -> list[str]:
    """Every reason live trading must be refused (empty list: allowed)."""
    problems = []
    if cfg.mode != "live":
        problems.append(f'config mode is "{cfg.mode}": set mode = "live" in the config to trade real orders')
    if env.get(LIVE_CONFIRM_ENV) != LIVE_CONFIRM_VALUE:
        problems.append(f"set {LIVE_CONFIRM_ENV}={LIVE_CONFIRM_VALUE} to confirm you accept the risk of real orders")
    unsupported = [f"{v.name} (feed {v.feed})" for v in cfg.venues if v.feed not in LIVE_CLIENT_FEEDS]
    if unsupported:
        problems.append(
            "no live order client for venue(s) " + ", ".join(unsupported)
            + ": only Binance spot (feed = \"binance\") has one in this version. Remove those venues "
            "from the config or use `arbbot paper`."
        )
    if any(v.feed == "binance" for v in cfg.venues):
        missing = [k for k in (BINANCE_KEY_ENV, BINANCE_SECRET_ENV) if not env.get(k, "").strip()]
        if missing:
            problems.append(f"Binance API credentials missing: set {' and '.join(missing)}")
        bad = [k for k in (BINANCE_KEY_ENV, BINANCE_SECRET_ENV)
               if k not in missing and _BAD_CREDENTIAL_CHARS.search(env[k].strip())]
        if bad:  # never echo the values
            problems.append(f"{' and '.join(bad)} must not contain whitespace or control characters")
    return problems


def build_live_clients(cfg: BotConfig, env: Mapping[str, str], *, mainnet: bool) -> dict[str, ExchangeClient]:
    """Binance spot clients for every venue (call only after ``live_problems`` came back empty).

    Credentials are stripped: a secret file's trailing newline is not part of the key.
    """
    base_url = MAINNET_URL if mainnet else TESTNET_URL
    key, secret = env[BINANCE_KEY_ENV].strip(), env[BINANCE_SECRET_ENV].strip()
    return {
        v.name: BinanceSpotClient(v, key, secret, base_url=base_url, allow_mainnet=mainnet)
        for v in cfg.venues
    }


def _load(path: str) -> BotConfig:
    try:
        return load_config(path)
    except FileNotFoundError:
        raise UsageError(f"config file not found: {path} (copy config.example.toml to start)") from None
    except tomllib.TOMLDecodeError as e:
        raise UsageError(f"{path}: invalid TOML: {e}") from None
    except ConfigError as e:
        raise UsageError(f"{path}: {e}") from None


async def _run_until_stopped(bot: Bot, feeds: Sequence[WebSocketFeed], duration_s: float | None) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):  # e.g. Windows, or not the main thread
            loop.add_signal_handler(sig, stop.set)
            installed.append(sig)
    timer = loop.call_later(duration_s, stop.set) if duration_s else None
    try:
        await bot.run(feeds, stop)
    finally:
        if timer is not None:
            timer.cancel()
        for sig in installed:
            loop.remove_signal_handler(sig)


def _print_summary(bot: Bot) -> None:
    print(json.dumps({
        "counters": bot.counters.summary(),
        "halted": bot.risk.halted,
        "halt_reason": bot.risk.halt_reason,
        "scanner": bot.scanner.stats.summary(),
    }, indent=2))


# --------------------------------------------------------------------------- commands


def cmd_trade(args: argparse.Namespace, mode: str, env: Mapping[str, str]) -> int:
    cfg = _load(args.config)
    clock = WallClock()
    binance_ws = None
    if mode == "live":
        problems = live_problems(cfg, env)
        if problems:
            raise UsageError("live trading refused:\n  - " + "\n  - ".join(problems))
        if not args.mainnet:
            binance_ws = BINANCE_TESTNET_WS  # trade the testnet book on testnet market data
    feeds = build_feeds(cfg, clock, binance_ws=binance_ws)
    book = QuoteBook()
    portfolio = portfolio_from_config(cfg)
    clients: dict[str, ExchangeClient] | None = None
    if mode == "paper":
        clients = build_paper_clients(cfg, book, clock, portfolio)
    elif mode == "live":
        clients = build_live_clients(cfg, env, mainnet=args.mainnet)
        where = "MAINNET (real money)" if args.mainnet else "Binance spot TESTNET"
        log.warning("LIVE TRADING on %s for venues %s", where, [v.name for v in cfg.venues])
        log.warning("balances are NOT read from the venue: starting_balances in the config must match your account")
    journal = Journal(args.journal or cfg.journal_path)
    alerter = alerter_from_env(env)
    bot = Bot(cfg, clients=clients, clock=clock, journal=journal, portfolio=portfolio,
              inline_execution=False, book=book, alerter=alerter, label=mode)
    log.info("%s: %d venue(s), journal %s; Ctrl-C to stop", mode, len(feeds), args.journal or cfg.journal_path)
    try:
        asyncio.run(_run_until_stopped(bot, feeds, args.duration))
    finally:
        journal.close()
        alerter.close()
    _print_summary(bot)
    return EXIT_OK


def cmd_record(args: argparse.Namespace) -> int:
    cfg = _load(args.config)
    if args.duration <= 0:
        raise UsageError("--duration must be > 0")
    clock = WallClock()
    feeds = build_feeds(cfg, clock)

    def stop_feeds() -> None:
        for f in feeds:
            f.stop()

    async def go() -> int:
        task = asyncio.ensure_future(record(feeds, args.out, args.duration, clock))
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, stop_feeds)
        return await task

    n = asyncio.run(go())
    print(f"recorded {n} quotes to {args.out}")
    return EXIT_OK


def cmd_backtest(args: argparse.Namespace) -> int:
    cfg = _load(args.config)
    try:
        quotes = load_quotes(args.data)
    except FileNotFoundError:
        raise UsageError(f"data file not found: {args.data}") from None
    except ValueError as e:
        raise UsageError(f"{args.data}: {e}") from None
    if not quotes:
        raise UsageError(f"{args.data}: no quotes")
    journal = Journal(args.journal) if args.journal else None
    try:
        result = run_backtest(cfg, quotes, journal=journal, journal_meta={"data": args.data, "config": args.config})
    finally:
        if journal is not None:
            journal.close()
    print(result.format_report())
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
        print(f"report written to {path}")
    return EXIT_OK


def cmd_synth(args: argparse.Namespace) -> int:
    venues = [v.strip() for v in args.venues.split(",") if v.strip()] if args.venues else []
    symbol = args.symbol
    if not (venues and symbol):
        cfg = _load(args.config)
        if not symbol:
            symbols = cfg.cross_venue_symbols()
            if not symbols:
                raise UsageError("no symbol is listed on two venues in the config: pass --symbol and --venues")
            symbol = symbols[0]
        if not venues:
            venues = [v.name for v in cfg.venues_for(symbol)]
    if len(venues) < 2:
        raise UsageError(f"need at least two venues for {symbol}, got {venues}")
    try:
        quotes = generate_synthetic(
            venues, symbol, start_ts=args.start_ts, duration_s=args.duration, hz=args.hz,
            base_price=args.base_price, vol_bps=args.vol_bps, spread_bps=args.spread_bps, depth=args.depth,
            dislocation_rate=args.dislocation_rate, dislocation_bps=args.dislocation_bps, seed=args.seed,
        )
    except ValueError as e:
        raise UsageError(str(e)) from None
    out = Path(args.out)
    with QuoteRecorder(out, append=False) as rec:  # a fresh file, never appended to an old one
        for q in quotes:
            rec.write(q)
    print(f"wrote {len(quotes)} synthetic {symbol} quotes for {', '.join(venues)} to {out}")
    return EXIT_OK


# --------------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="arbbot", description="Cross-venue arbitrage scanner and execution engine.")
    p.add_argument("--version", action="version", version=f"arbbot {__version__}")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def with_config(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("-c", "--config", default="config.toml", help="TOML config (default: config.toml)")

    for name, text in (
        ("scan", "live feeds; journal signals and risk decisions, never place orders"),
        ("paper", "live feeds; simulated fills against the live book (after venue latency)"),
        ("live", "real orders (Binance spot only; testnet unless --mainnet); heavily gated"),
    ):
        sp = sub.add_parser(name, help=text, description=text)
        with_config(sp)
        sp.add_argument("--duration", type=float, default=None, help="stop after this many seconds")
        sp.add_argument("--journal", default=None, help="journal JSONL path (default: journal_path from config)")
        if name == "live":
            sp.add_argument("--mainnet", action="store_true", help="trade on Binance MAINNET (real money)")

    sp = sub.add_parser("record", help="record live quotes to JSONL")
    with_config(sp)
    sp.add_argument("--out", required=True, help="output JSONL path (appended to)")
    sp.add_argument("--duration", type=float, required=True, help="seconds to record")

    sp = sub.add_parser("backtest", help="replay recorded quotes with paper fills")
    with_config(sp)
    sp.add_argument("--data", required=True, help="quote file: recorder JSONL or CSV")
    sp.add_argument("--report", default=None, help="also write the full result as JSON here")
    sp.add_argument("--journal", default=None,
                    help="append the run's journal JSONL here (bracketed by start/shutdown records)")

    sp = sub.add_parser("synth", help="write synthetic quotes (demo/testing only)")
    with_config(sp)
    sp.add_argument("--out", required=True, help="output JSONL path (overwritten)")
    sp.add_argument("--symbol", default=None, help="canonical symbol (default: first cross-venue symbol in config)")
    sp.add_argument("--venues", default=None, help="comma-separated venue names (default: venues listing the symbol)")
    sp.add_argument("--duration", type=float, default=600.0, help="seconds of data (default 600)")
    sp.add_argument("--hz", type=float, default=10.0, help="quotes per second per venue (default 10)")
    sp.add_argument("--base-price", type=float, default=50000.0, help="starting mid (synthetic, not a market price)")
    sp.add_argument("--vol-bps", type=float, default=2.0, help="random-walk volatility, bps per sqrt(second)")
    sp.add_argument("--spread-bps", type=float, default=1.0, help="quoted spread in bps (default 1)")
    sp.add_argument("--depth", type=float, default=1.0, help="mean top-of-book size, base units (default 1)")
    sp.add_argument("--dislocation-rate", type=float, default=0.02, help="dislocations per second (default 0.02)")
    sp.add_argument("--dislocation-bps", type=float, default=40.0, help="dislocation size in bps (default 40)")
    sp.add_argument("--seed", type=int, default=7)
    sp.add_argument("--start-ts", type=float, default=SYNTH_START_TS, help="first timestamp (epoch s)")
    return p


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:  # argparse exits 2 on usage errors, 0 on --help
        return int(e.code) if isinstance(e.code, int) else EXIT_USAGE
    env = os.environ if env is None else env
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        if args.command in ("scan", "paper", "live"):
            return cmd_trade(args, args.command, env)
        if args.command == "record":
            return cmd_record(args)
        if args.command == "backtest":
            return cmd_backtest(args)
        if args.command == "synth":
            return cmd_synth(args)
        parser.error(f"unknown command {args.command!r}")  # unreachable: subparsers are required
    except UsageError as e:
        print(f"arbbot: error: {e}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        return EXIT_OK
    except Exception:
        log.exception("arbbot %s failed", args.command)
        return EXIT_FAILURE
    return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
