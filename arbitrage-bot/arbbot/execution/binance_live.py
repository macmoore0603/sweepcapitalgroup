"""Binance spot REST client: signed LIMIT IOC orders implementing ``ExchangeClient``.

Everything here follows the official spot API docs
(https://github.com/binance/binance-spot-api-docs, ``rest-api.md``,
``errors.md``, ``enums.md``; testnet: ``testnet/rest-api.md``):

* ``POST /api/v3/order`` with ``type=LIMIT``, ``timeInForce=IOC``, ``quantity``,
  ``price``, ``newClientOrderId`` and ``newOrderRespType=FULL`` (fills with
  ``price``, ``qty``, ``commission``, ``commissionAsset``).
* ``GET /api/v3/order`` by ``symbol`` + ``origClientOrderId`` to reconcile. Its
  response has no ``fills``, so the fee of a reconciled order is estimated.
* SIGNED requests: ``timestamp`` (ms) and ``recvWindow`` (default 5000, max
  60000) in the query string, ``signature`` = hex HMAC-SHA256 of the exact
  query string (+ body, which we leave empty) keyed by the secret, and the
  API key in the ``X-MBX-APIKEY`` header.
* HTTP 4XX: the request was refused (sender side, WAF, rate limit) ->
  ``REJECTED``. HTTP 5XX: "the execution status is UNKNOWN and could have been
  a success" -> ``ExchangeError`` so the engine reconciles. Error codes -1000
  (UNKNOWN), -1006 (UNEXPECTED_RESP, "execution status unknown") and -1007
  (TIMEOUT, "execution status unknown") are treated as unknown at any HTTP
  status. On query, -2013 (NO_SUCH_ORDER) -> None and -2026 (ORDER_ARCHIVED:
  "canceled or expired with no executed qty") -> an unfilled EXPIRED result.
* IOC terminal statuses: ``FILLED``; ``EXPIRED`` (with ``executedQty`` > 0 when
  partially filled); ``EXPIRED_IN_MATCH`` (self-trade prevention).
* Client order ids are restricted to ``^[A-Za-z0-9_-]{1,36}$``, the rule the
  official FIX API doc states for Binance client order ids (the REST doc does
  not spell one out; this set is accepted everywhere).

Fees are reported in the quote currency: commission in the quote asset as is,
in the base asset times the fill price, in any other asset (e.g. BNB) estimated
as ``fill notional * venue.taker_fee_bps / 1e4`` with a note (``notes_for``).
Binance deducts commission from the asset received ("for BUY orders the
received amount is the quantity", spot commission FAQ), so a BUY without BNB
credits ``executedQty - commission``: the base part is also reported in base
units as ``OrderResult.base_fee``, and the engine opens/sells only what the
account received. A reconciled order (``GET /api/v3/order`` has no fills) has
an unknown commission asset; for a BUY it is assumed taken in base, so a
position never tries to sell more than the account holds.

Credentials containing whitespace or control characters (e.g. the trailing
newline of a secret file) are refused at construction: an invalid header value
would otherwise put the key into the exception text. Transport exceptions
other than ``TransportError`` are reported by type name only.

Testnet (``https://testnet.binance.vision``) is the default; any other base URL
trades real money and needs ``allow_mainnet=True``. The API key and secret
never appear in reprs, logs, exception messages or rejection errors.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import http.client
import json
import logging
import math
import re
import urllib.error
import urllib.request
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from ..clock import Clock, WallClock
from ..config import InstrumentConfig, VenueConfig
from ..models import OrderRequest, OrderResult, OrderStatus, Side, split_symbol
from .base import ExchangeError

log = logging.getLogger(__name__)

TESTNET_URL = "https://testnet.binance.vision"
MAINNET_URL = "https://api.binance.com"
TESTNET_HOST = "testnet.binance.vision"
ORDER_PATH = "/api/v3/order"
API_KEY_HEADER = "X-MBX-APIKEY"
MAX_RECV_WINDOW_MS = 60000.0
DEFAULT_TIMEOUT_S = 10.0  # Binance's own processing timeout is 10 s

CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,36}$")
_BAD_CREDENTIAL_CHARS = re.compile(r"[\s\x00-\x1f\x7f]")

# Binance error codes (errors.md).
NO_SUCH_ORDER = -2013
ORDER_ARCHIVED = -2026
UNKNOWN_STATE_CODES = frozenset({-1000, -1006, -1007})

_TERMINAL = frozenset({"FILLED", "EXPIRED", "EXPIRED_IN_MATCH", "CANCELED", "REJECTED"})
_MAX_NOTES = 1000
_REDACTED = "***"


# --------------------------------------------------------------------------- formatting / signing


def to_decimal(x: float | str | Decimal) -> Decimal:
    """Exact decimal of a float's shortest repr (0.1 -> Decimal('0.1'), not the binary expansion)."""
    if isinstance(x, Decimal):
        d = x
    elif isinstance(x, float):
        d = Decimal(repr(x))
    else:
        d = Decimal(str(x))
    if not d.is_finite():
        raise ValueError(f"not a finite number: {x!r}")
    return d


def format_decimal(x: float | str | Decimal) -> str:
    """Plain decimal string, never scientific notation: 1e-05 -> '0.00001', 3e4 -> '30000'."""
    s = format(to_decimal(x).normalize(), "f")
    return "0" if s == "-0" else s


def snap(value: float, step: float, rounding: str) -> Decimal:
    """``value`` on the ``step`` grid (exact Decimal arithmetic), rounding as given."""
    d, s = to_decimal(value), to_decimal(step)
    return (d / s).to_integral_value(rounding=rounding) * s


def encode_params(params: Sequence[tuple[str, str]]) -> str:
    """``k=v&...`` in the given order, percent-encoded (RFC 3986, UTF-8) as Binance signs it."""
    return urlencode(list(params), quote_via=quote)


def sign(secret: str, payload: str) -> str:
    """Hex HMAC-SHA256 of ``payload`` keyed by the API secret."""
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def signed_query(params: Sequence[tuple[str, str]], secret: str) -> str:
    """The query string with ``&signature=...`` appended (signature over the exact string sent)."""
    qs = encode_params(params)
    return f"{qs}&signature={sign(secret, qs)}"


# --------------------------------------------------------------------------- transport


@dataclass(frozen=True, slots=True, repr=False)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes = b""

    def __repr__(self) -> str:
        path = urlsplit(self.url).path
        hdrs = {k: (_REDACTED if k.lower() == API_KEY_HEADER.lower() else v) for k, v in self.headers.items()}
        return f"HttpRequest({self.method} {path}, headers={hdrs})"


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes


class TransportError(Exception):
    """The request may or may not have reached Binance (timeout, reset, DNS, TLS...)."""


Transport = Callable[[HttpRequest], Awaitable[HttpResponse]]


class UrllibTransport:
    """Stdlib HTTP via a worker thread. Every HTTP status is returned; network failures raise TransportError."""

    def __init__(self, timeout_s: float = DEFAULT_TIMEOUT_S, *, opener: urllib.request.OpenerDirector | None = None):
        self._timeout_s = timeout_s
        self._opener = opener or urllib.request.build_opener()

    async def __call__(self, req: HttpRequest) -> HttpResponse:
        return await asyncio.to_thread(self._send, req)

    def _send(self, req: HttpRequest) -> HttpResponse:
        r = urllib.request.Request(
            req.url,
            data=req.body if req.method != "GET" else None,
            headers=dict(req.headers),
            method=req.method,
        )
        try:
            with self._opener.open(r, timeout=self._timeout_s) as resp:
                return HttpResponse(resp.status, resp.read())
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
            except (OSError, http.client.HTTPException):
                body = b""
            finally:
                e.close()
            return HttpResponse(e.code, body)
        except (OSError, http.client.HTTPException) as e:  # TimeoutError and URLError are OSErrors
            reason = getattr(e, "reason", None) or e
            raise TransportError(f"{type(e).__name__}: {reason}") from None


# --------------------------------------------------------------------------- client


class _Credentials:
    """Holds the API key pair; its repr never shows them."""

    __slots__ = ("api_key", "secret")

    def __init__(self, api_key: str, secret: str) -> None:
        self.api_key = api_key
        self.secret = secret

    def __repr__(self) -> str:
        return "<credentials redacted>"

    def scrub(self, text: str) -> str:
        """``text`` without either secret, also in stripped or escaped (``repr``) form."""
        forms = set()
        for s in (self.api_key, self.secret):
            if s:
                forms |= {s, s.strip(), repr(s)[1:-1], s.encode("unicode_escape").decode("ascii")}
        for form in sorted((f for f in forms if f), key=len, reverse=True):
            text = text.replace(form, _REDACTED)
        return text


@dataclass(frozen=True, slots=True)
class _ApiError:
    status: int
    code: int | None
    msg: str

    def describe(self) -> str:
        code = f" code {self.code}" if self.code is not None else ""
        return f"HTTP {self.status}{code}: {self.msg}"


class BinanceSpotClient:
    """``ExchangeClient`` for one Binance spot account (testnet unless ``allow_mainnet``)."""

    def __init__(
        self,
        venue: VenueConfig,
        api_key: str,
        api_secret: str,
        *,
        base_url: str = TESTNET_URL,
        allow_mainnet: bool = False,
        transport: Transport | None = None,
        clock: Clock | None = None,
        recv_window_ms: float = 5000.0,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        if not api_key or not api_secret:
            raise ValueError("Binance API key and secret are required")
        if _BAD_CREDENTIAL_CHARS.search(api_key) or _BAD_CREDENTIAL_CHARS.search(api_secret):
            # The values themselves are never echoed.
            raise ValueError("Binance API key and secret must not contain whitespace or control characters "
                             "(a secret file's trailing newline?)")
        parts = urlsplit(base_url)
        if parts.scheme != "https" or not parts.hostname or parts.path not in ("", "/") or parts.query:
            raise ValueError(f"base_url must be an https origin like {TESTNET_URL!r}, got {base_url!r}")
        self.is_testnet = parts.hostname == TESTNET_HOST
        if not self.is_testnet and not allow_mainnet:
            raise ValueError(
                f"refusing to trade real money on {parts.hostname}: pass allow_mainnet=True "
                f"(testnet is {TESTNET_URL})"
            )
        if not 0 < recv_window_ms <= MAX_RECV_WINDOW_MS:
            raise ValueError(f"recv_window_ms must be in (0, {MAX_RECV_WINDOW_MS:g}], got {recv_window_ms}")
        self.venue = venue.name
        self.config = venue
        self.base_url = f"{parts.scheme}://{parts.netloc}"
        self._creds = _Credentials(api_key, api_secret)
        self._transport: Transport = transport or UrllibTransport(timeout_s)
        self._clock: Clock = clock or WallClock()
        self._recv_window = format_decimal(recv_window_ms)
        self._notes: OrderedDict[str, list[str]] = OrderedDict()

    def __repr__(self) -> str:
        net = "testnet" if self.is_testnet else "MAINNET"
        return f"BinanceSpotClient(venue={self.venue!r}, base_url={self.base_url!r}, {net})"

    __str__ = __repr__

    def notes_for(self, client_id: str) -> tuple[str, ...]:
        """Fee estimates and other caveats recorded for an order (e.g. commission paid in BNB)."""
        return tuple(self._notes.get(client_id, ()))

    # ------------------------------------------------------------------ ExchangeClient

    async def place_ioc(self, req: OrderRequest) -> OrderResult:
        problem = self._validate(req)
        inst = self.config.instrument(req.symbol)
        if problem is not None or inst is None:
            log.warning("binance: not sending %s: %s", req.client_id, problem)
            return self._result(req, OrderStatus.REJECTED, error=problem or "symbol not configured")
        qty = snap(req.qty, inst.lot_size, ROUND_FLOOR)
        # Never more aggressive than requested: BUY limits round down, SELL limits round up.
        price = snap(req.limit_price, inst.tick_size, ROUND_FLOOR if req.side is Side.BUY else ROUND_CEILING)
        if qty <= 0 or price <= 0:
            return self._result(req, OrderStatus.REJECTED, error=f"qty {req.qty} / price {req.limit_price} "
                                f"is zero on the venue grid (lot {inst.lot_size}, tick {inst.tick_size})")
        params = [
            ("symbol", inst.venue_symbol),
            ("side", req.side.value.upper()),
            ("type", "LIMIT"),
            ("timeInForce", "IOC"),
            ("quantity", format_decimal(qty)),
            ("price", format_decimal(price)),
            ("newClientOrderId", req.client_id),
            ("newOrderRespType", "FULL"),
        ]
        what = f"POST {ORDER_PATH} {req.client_id}"
        resp = await self._signed("POST", params, what)
        if 200 <= resp.status < 300:
            data = self._json(resp, what)
            result = self._parse_order(req, inst, data, what, from_query=False)
        else:
            err = self._api_error(resp)
            if resp.status >= 500 or err.code in UNKNOWN_STATE_CODES:
                raise ExchangeError(self._scrub(f"binance {what}: {err.describe()}; execution status unknown"))
            result = self._result(req, OrderStatus.REJECTED, error=self._scrub(f"binance {err.describe()}"))
        log.info("binance: %s %s %s qty=%s px=%s -> %s filled=%s avg=%s fee=%s",
                 req.client_id, inst.venue_symbol, req.side.value, format_decimal(qty), format_decimal(price),
                 result.status.value, result.filled_qty, result.avg_price, result.fee)
        return result

    async def query_order(self, req: OrderRequest) -> OrderResult | None:
        """Final state of ``req.client_id``; None when Binance answers -2013 (no such order).

        A query that fails for any other reason raises ``ExchangeError``: returning
        REJECTED or None would assert that nothing filled, which we do not know.
        """
        inst = self.config.instrument(req.symbol)
        if inst is None or CLIENT_ID_RE.fullmatch(req.client_id) is None:
            return None  # place_ioc never sends such an order
        params = [("symbol", inst.venue_symbol), ("origClientOrderId", req.client_id)]
        what = f"GET {ORDER_PATH} {req.client_id}"
        resp = await self._signed("GET", params, what)
        if 200 <= resp.status < 300:
            return self._parse_order(req, inst, self._json(resp, what), what, from_query=True)
        err = self._api_error(resp)
        if 400 <= resp.status < 500 and err.code == NO_SUCH_ORDER:
            return None
        if 400 <= resp.status < 500 and err.code == ORDER_ARCHIVED:
            self._note(req.client_id, f"order archived by Binance ({err.msg}): expired with no executed qty")
            return self._result(req, OrderStatus.EXPIRED)
        raise ExchangeError(self._scrub(f"binance {what}: {err.describe()}; order state unknown"))

    # ------------------------------------------------------------------ request plumbing

    def _validate(self, req: OrderRequest) -> str | None:
        if req.venue != self.venue:
            return f"order for venue {req.venue!r} sent to {self.venue!r}"
        if req.tif != "IOC":
            return f"only IOC orders are supported, got {req.tif!r}"
        if CLIENT_ID_RE.fullmatch(req.client_id) is None:
            return f"client id {req.client_id!r} must match {CLIENT_ID_RE.pattern}"
        if not (math.isfinite(req.qty) and req.qty > 0 and math.isfinite(req.limit_price) and req.limit_price > 0):
            return f"qty {req.qty} and limit {req.limit_price} must be positive and finite"
        if self.config.instrument(req.symbol) is None:
            return f"{req.symbol} is not configured on {self.venue}"
        return None

    async def _signed(self, method: str, params: list[tuple[str, str]], what: str) -> HttpResponse:
        ts_ms = round(self._clock.now() * 1000)
        params = [*params, ("recvWindow", self._recv_window), ("timestamp", str(ts_ms))]
        url = f"{self.base_url}{ORDER_PATH}?{signed_query(params, self._creds.secret)}"
        request = HttpRequest(method, url, {API_KEY_HEADER: self._creds.api_key})
        try:
            return await self._transport(request)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - any transport failure leaves the order's fate unknown
            # ``from None`` and no foreign exception text: it could carry request details (headers, the key).
            detail = f"{type(e).__name__}: {e}" if isinstance(e, TransportError) else type(e).__name__
            raise ExchangeError(self._scrub(f"binance {what}: {detail}; state unknown")) from None

    def _json(self, resp: HttpResponse, what: str) -> dict[str, Any]:
        try:
            data = json.loads(resp.body)
        except (ValueError, UnicodeDecodeError):
            data = None
        if not isinstance(data, dict):
            raise ExchangeError(f"binance {what}: HTTP {resp.status} with an unparseable body; state unknown")
        return data

    def _api_error(self, resp: HttpResponse) -> _ApiError:
        try:
            data = json.loads(resp.body)
        except (ValueError, UnicodeDecodeError):
            data = None
        if isinstance(data, dict) and isinstance(data.get("code"), int):
            return _ApiError(resp.status, data["code"], str(data.get("msg", "")))
        text = resp.body[:200].decode("utf-8", "replace").strip()
        return _ApiError(resp.status, None, text or "(empty body)")

    def _scrub(self, text: str) -> str:
        return self._creds.scrub(text)

    def _note(self, client_id: str, note: str) -> None:
        self._notes.setdefault(client_id, []).append(note)
        self._notes.move_to_end(client_id)
        while len(self._notes) > _MAX_NOTES:
            self._notes.popitem(last=False)
        log.info("binance: %s: %s", client_id, note)

    # ------------------------------------------------------------------ response parsing

    def _result(self, req: OrderRequest, status: OrderStatus, *, filled: float = 0.0, avg: float = 0.0,
                fee: float = 0.0, base_fee: float = 0.0, error: str | None = None) -> OrderResult:
        return OrderResult(
            client_id=req.client_id,
            venue=self.venue,
            symbol=req.symbol,
            side=req.side,
            requested_qty=req.qty,
            filled_qty=filled,
            avg_price=avg,
            fee=fee,
            status=status,
            ts=self._clock.now(),
            error=error,
            base_fee=base_fee,
        )

    def _parse_order(self, req: OrderRequest, inst: InstrumentConfig, data: Mapping[str, Any], what: str,
                     *, from_query: bool) -> OrderResult:
        try:
            if data.get("symbol") != inst.venue_symbol or data.get("clientOrderId") != req.client_id:
                raise ExchangeError(
                    f"binance {what}: response is for {data.get('symbol')}/{data.get('clientOrderId')}; state unknown"
                )
            status = str(data["status"])
            executed = Decimal(str(data["executedQty"]))
            orig = Decimal(str(data["origQty"]))
            cumm_quote = Decimal(str(data["cummulativeQuoteQty"]))
            fills = data.get("fills") or []
            avg = self._avg_price(req, executed, cumm_quote, fills, Decimal(str(data.get("price", "0"))))
            fee, base_fee = self._fee(req, executed, avg, fills, from_query=from_query)
        except ExchangeError:
            raise
        except (KeyError, TypeError, ValueError, InvalidOperation, ArithmeticError):
            raise ExchangeError(f"binance {what}: malformed order response; state unknown") from None

        if status == "REJECTED":
            return self._result(req, OrderStatus.REJECTED, error="binance order status REJECTED")
        if status not in _TERMINAL:
            if not from_query:
                raise ExchangeError(f"binance {what}: IOC order still {status}; reconcile")
            return self._result(req, OrderStatus.UNKNOWN, filled=float(executed), avg=float(avg), fee=float(fee),
                                base_fee=float(base_fee), error=f"order still {status} on Binance; final fill unknown")
        if status == "EXPIRED_IN_MATCH":
            self._note(req.client_id, "expired by self-trade prevention (EXPIRED_IN_MATCH)")
        if executed <= 0:
            return self._result(req, OrderStatus.EXPIRED)
        out = OrderStatus.FILLED if status == "FILLED" and executed >= orig else OrderStatus.PARTIALLY_FILLED
        return self._result(req, out, filled=float(executed), avg=float(avg), fee=float(fee),
                            base_fee=float(base_fee))

    def _avg_price(self, req: OrderRequest, executed: Decimal, cumm_quote: Decimal,
                   fills: Sequence[Mapping[str, Any]], limit: Decimal) -> Decimal:
        if executed <= 0:
            return Decimal(0)
        if cumm_quote >= 0:
            return cumm_quote / executed
        # "For some historical orders cummulativeQuoteQty will be < 0" (data not available).
        if fills:
            notional = sum((Decimal(str(f["price"])) * Decimal(str(f["qty"])) for f in fills), Decimal(0))
            return notional / executed
        self._note(req.client_id, f"average price unavailable; using the order price {limit}")
        return limit

    def _fee(self, req: OrderRequest, executed: Decimal, avg: Decimal, fills: Sequence[Mapping[str, Any]],
             *, from_query: bool) -> tuple[Decimal, Decimal]:
        """(total commission in the quote currency, the part of it taken in the base asset, in base units)."""
        if executed <= 0:
            return Decimal(0), Decimal(0)
        base, quote_ccy = split_symbol(req.symbol)
        rate = to_decimal(self.config.taker_fee_bps) / Decimal(10000)
        if from_query or not fills:
            est = executed * avg * rate
            self._note(req.client_id, f"fee estimated as {format_decimal(est)} {quote_ccy} from taker_fee_bps="
                                      f"{self.config.taker_fee_bps} (no commission data in the response)")
            if req.side is Side.BUY:
                base_est = executed * rate
                self._note(req.client_id, f"commission asset unknown: assumed {format_decimal(base_est)} {base} "
                                          "taken from the base received, so the position never sells more than "
                                          "the account holds")
                return est, base_est
            return est, Decimal(0)
        fee = Decimal(0)
        base_fee = Decimal(0)
        for f in fills:
            price, qty = Decimal(str(f["price"])), Decimal(str(f["qty"]))
            commission, asset = Decimal(str(f["commission"])), str(f["commissionAsset"])
            if commission == 0:
                continue
            if asset == quote_ccy:
                fee += commission
            elif asset == base:
                fee += commission * price
                base_fee += commission
            else:
                est = price * qty * rate
                fee += est
                self._note(req.client_id, f"commission {format_decimal(commission)} {asset} estimated as "
                                          f"{format_decimal(est)} {quote_ccy} from taker_fee_bps="
                                          f"{self.config.taker_fee_bps}")
        return fee, base_fee


__all__ = [
    "API_KEY_HEADER",
    "MAINNET_URL",
    "TESTNET_URL",
    "BinanceSpotClient",
    "HttpRequest",
    "HttpResponse",
    "Transport",
    "TransportError",
    "UrllibTransport",
    "encode_params",
    "format_decimal",
    "sign",
    "signed_query",
]
