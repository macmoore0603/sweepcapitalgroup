"""Tests for arbbot.execution.binance_live.BinanceSpotClient (no network: injected fake transport).

Facts checked against the official spot API docs (binance-spot-api-docs:
rest-api.md, errors.md, enums.md, testnet/rest-api.md, fix-api.md):

* HMAC example (rest-api.md, "SIGNED Endpoint Examples for POST /api/v3/order"):
  apiKey ``vmPUZE6m...uEh8A``, secretKey ``NhqPtmdS...fATj0j``; the payload
  ``symbol=LTCBTC&...&timestamp=1499827319559`` signs to ``c8db5682...6b71`` and
  the percent-encoded non-ASCII payload (symbol ``１２３４５６``) to ``e1353ec6...3ef3``.
* FULL response fields: status, origQty, executedQty, cummulativeQuoteQty,
  fills[].price/qty/commission/commissionAsset. Query order has no fills.
* Error body ``{"code": <int>, "msg": <str>}``; -2013 "Order does not exist.",
  -2026 order archived (no executed qty), -1007 / -1006 "execution status unknown".
* HTTP 451 body below is a real testnet response observed from this sandbox
  (geo-restricted), i.e. a genuine 4XX with a Binance-shaped JSON error.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar
from urllib.parse import parse_qsl, urlsplit

import pytest

from arbbot.clock import SimClock
from arbbot.config import InstrumentConfig, VenueConfig
from arbbot.execution.base import ExchangeError
from arbbot.execution.binance_live import (
    API_KEY_HEADER,
    MAINNET_URL,
    TESTNET_URL,
    BinanceSpotClient,
    HttpRequest,
    HttpResponse,
    TransportError,
    UrllibTransport,
    format_decimal,
    sign,
    signed_query,
)
from arbbot.models import OrderRequest, OrderStatus, Side

# Example credentials published in Binance's docs (illustrative only, not a real account).
DOC_API_KEY = "vmPUZE6mv9SD5VNHk4HlWFsOr6aKE2zvsw0MuIgwCIPy6utIco14y7Ju91duEh8A"
DOC_SECRET = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"

T_MS = 1499827319559
T_S = T_MS / 1000  # the doc example's timestamp, as Clock seconds

GEO_BLOCK_451 = {
    "code": 0,
    "msg": "Service unavailable from a restricted location according to 'b. Eligibility' in "
           "https://www.binance.com/en/terms. Please contact customer service if you believe you "
           "received this message in error.",
}


# --------------------------------------------------------------------------- fixtures


def venue_cfg(**kw) -> VenueConfig:
    insts = (
        InstrumentConfig(symbol="BTC-USDT", venue_symbol="BTCUSDT", tick_size=0.01, lot_size=0.00001),
        InstrumentConfig(symbol="DOGE-BTC", venue_symbol="DOGEBTC", tick_size=1e-08, lot_size=1e-05),
    )
    return VenueConfig(name="binance", feed="binance", taker_fee_bps=kw.get("fee", 10.0), instruments=insts)


class FakeTransport:
    """Returns (or raises) scripted responses in order and records every request."""

    def __init__(self, *responses: HttpResponse | BaseException) -> None:
        self.responses = list(responses)
        self.requests: list[HttpRequest] = []

    async def __call__(self, req: HttpRequest) -> HttpResponse:
        self.requests.append(req)
        r = self.responses.pop(0)
        if isinstance(r, BaseException):
            raise r
        return r


def resp(status: int, body: object) -> HttpResponse:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return HttpResponse(status, raw)


def client(*responses: HttpResponse | BaseException, **kw) -> tuple[BinanceSpotClient, FakeTransport]:
    t = FakeTransport(*responses)
    c = BinanceSpotClient(venue_cfg(), DOC_API_KEY, DOC_SECRET, transport=t, clock=SimClock(T_S), **kw)
    return c, t


def order(side: Side = Side.BUY, qty: float = 0.002, limit: float = 30010.0, *, cid: str = "arb-1",
          symbol: str = "BTC-USDT", tif: str = "IOC", venue: str = "binance") -> OrderRequest:
    return OrderRequest(client_id=cid, venue=venue, symbol=symbol, side=side, qty=qty, limit_price=limit, tif=tif)


def full_response(status: str, *, side: str = "BUY", orig: str = "0.00200000", executed: str = "0.00000000",
                  cumm: str = "0.00000000", fills: list[dict] | None = None, cid: str = "arb-1",
                  symbol: str = "BTCUSDT", price: str = "30010.00000000") -> dict:
    return {
        "symbol": symbol, "orderId": 28, "orderListId": -1, "clientOrderId": cid,
        "transactTime": T_MS, "price": price, "origQty": orig, "executedQty": executed,
        "origQuoteOrderQty": "0.00000000", "cummulativeQuoteQty": cumm, "status": status,
        "timeInForce": "IOC", "type": "LIMIT", "side": side, "workingTime": T_MS,
        "selfTradePreventionMode": "EXPIRE_MAKER", "fills": fills or [],
    }


def fill(price: str, qty: str, commission: str, asset: str, trade_id: int = 56) -> dict:
    return {"price": price, "qty": qty, "commission": commission, "commissionAsset": asset, "tradeId": trade_id}


def query_params(req: HttpRequest) -> list[tuple[str, str]]:
    return parse_qsl(urlsplit(req.url).query, keep_blank_values=True)


# --------------------------------------------------------------------------- signing (doc vectors)


def test_signature_matches_binance_doc_example_ascii():
    payload = ("symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1"
               "&recvWindow=5000&timestamp=1499827319559")
    assert sign(DOC_SECRET, payload) == "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"


def test_signed_query_percent_encodes_then_signs_like_binance_doc_non_ascii():
    params = [("symbol", "１２３４５６"), ("side", "BUY"), ("type", "LIMIT"), ("timeInForce", "GTC"),
              ("quantity", "1"), ("price", "0.1"), ("recvWindow", "5000"), ("timestamp", "1499827319559")]
    assert signed_query(params, DOC_SECRET) == (
        "symbol=%EF%BC%91%EF%BC%92%EF%BC%93%EF%BC%94%EF%BC%95%EF%BC%96&side=BUY&type=LIMIT&timeInForce=GTC"
        "&quantity=1&price=0.1&recvWindow=5000&timestamp=1499827319559"
        "&signature=e1353ec6b14d888f1164ae9af8228a3dbd508bc82eb867db8ab6046442f33ef3"
    )


# --------------------------------------------------------------------------- request shape


async def test_place_ioc_request_params_headers_and_signature():
    c, t = client(resp(200, full_response("EXPIRED", orig="0.00150000", price="30123.45000000")))
    await c.place_ioc(order(qty=0.0015, limit=30123.45))
    (req,) = t.requests
    qs = ("symbol=BTCUSDT&side=BUY&type=LIMIT&timeInForce=IOC&quantity=0.0015&price=30123.45"
          "&newClientOrderId=arb-1&newOrderRespType=FULL&recvWindow=5000&timestamp=1499827319559")
    expected_sig = hmac.new(DOC_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
    assert req.method == "POST"
    assert req.url == f"https://testnet.binance.vision/api/v3/order?{qs}&signature={expected_sig}"
    assert dict(req.headers) == {"X-MBX-APIKEY": DOC_API_KEY}
    assert req.body == b""  # everything is in the signed query string


async def test_sell_side_and_custom_recv_window():
    c, t = client(resp(200, full_response("EXPIRED", side="SELL")), recv_window_ms=2500.5)
    await c.place_ioc(order(Side.SELL))
    params = dict(query_params(t.requests[0]))
    assert params["side"] == "SELL" and params["recvWindow"] == "2500.5"


# --------------------------------------------------------------------------- response mapping


async def test_filled_full_response_avg_price_and_fees_in_quote():
    fills = [
        fill("30000.00000000", "0.00120000", "0.00000120", "BTC"),  # base commission * fill price = 0.036
        fill("30005.00000000", "0.00080000", "0.02400400", "USDT", 57),  # quote commission as is
    ]
    body = full_response("FILLED", executed="0.00200000", cumm="60.00400000", fills=fills)
    c, _ = client(resp(200, body))
    r = await c.place_ioc(order())
    assert r.status is OrderStatus.FILLED
    assert (r.client_id, r.venue, r.symbol, r.side) == ("arb-1", "binance", "BTC-USDT", Side.BUY)
    assert r.requested_qty == 0.002 and r.filled_qty == 0.002
    assert r.avg_price == 30002.0  # 60.004 / 0.002
    assert r.fee == 0.060004  # 0.0000012 * 30000 + 0.024004
    assert r.ts == T_S and r.error is None
    assert c.notes_for("arb-1") == ()


async def test_partial_expired_with_bnb_commission_is_estimated_from_taker_fee():
    fills = [fill("29990.00000000", "0.00100000", "0.00005000", "BNB")]
    body = full_response("EXPIRED", side="SELL", orig="0.00300000", executed="0.00100000",
                         cumm="29.99000000", fills=fills, price="29980.00000000")
    c, t = client(resp(200, body))
    r = await c.place_ioc(order(Side.SELL, qty=0.003, limit=29980.0))
    assert dict(query_params(t.requests[0]))["price"] == "29980"
    assert r.status is OrderStatus.PARTIALLY_FILLED
    assert r.filled_qty == 0.001 and r.remaining_qty == pytest.approx(0.002)
    assert r.avg_price == 29990.0
    assert r.fee == 0.02999  # 29.99 notional * 10 bps
    (note,) = c.notes_for("arb-1")
    assert "BNB" in note and "0.02999 USDT" in note and "taker_fee_bps=10.0" in note


async def test_zero_commission_in_foreign_asset_needs_no_estimate():
    fills = [fill("30000.00000000", "0.00200000", "0.00000000", "BNB")]
    c, _ = client(resp(200, full_response("FILLED", executed="0.00200000", cumm="60.00000000", fills=fills)))
    r = await c.place_ioc(order())
    assert r.fee == 0.0 and c.notes_for("arb-1") == ()


async def test_expired_with_nothing_filled():
    c, _ = client(resp(200, full_response("EXPIRED")))
    r = await c.place_ioc(order())
    assert r.status is OrderStatus.EXPIRED
    assert (r.filled_qty, r.avg_price, r.fee) == (0.0, 0.0, 0.0)


async def test_expired_in_match_maps_by_executed_qty_and_notes_stp():
    c, _ = client(resp(200, full_response("EXPIRED_IN_MATCH")))
    r = await c.place_ioc(order())
    assert r.status is OrderStatus.EXPIRED
    assert any("EXPIRED_IN_MATCH" in n for n in c.notes_for("arb-1"))


async def test_4xx_binance_error_is_rejected():
    c, _ = client(resp(400, {"code": -2010, "msg": "Account has insufficient balance for requested action."}))
    r = await c.place_ioc(order())
    assert r.status is OrderStatus.REJECTED and r.filled_qty == 0.0
    assert r.error == "binance HTTP 400 code -2010: Account has insufficient balance for requested action."


async def test_real_geo_block_451_is_rejected():
    c, _ = client(resp(451, GEO_BLOCK_451))
    r = await c.place_ioc(order())
    assert r.status is OrderStatus.REJECTED
    assert r.error.startswith("binance HTTP 451 code 0: Service unavailable from a restricted location")


@pytest.mark.parametrize("status, body", [(429, {"code": -1003, "msg": "Too much request weight used"}),
                                          (403, b"<html>WAF</html>"), (418, b"")])
async def test_rate_limit_and_waf_4xx_are_rejected(status, body):
    c, _ = client(resp(status, body))
    r = await c.place_ioc(order())
    assert r.status is OrderStatus.REJECTED and f"HTTP {status}" in r.error


@pytest.mark.parametrize("status, body", [(500, b""), (502, b"<html>bad gateway</html>"),
                                          (503, {"code": -1001, "msg": "Internal error"})])
async def test_5xx_raises_exchange_error_state_unknown(status, body):
    c, _ = client(resp(status, body))
    with pytest.raises(ExchangeError, match=f"HTTP {status}.*unknown"):
        await c.place_ioc(order())


@pytest.mark.parametrize("code", [-1000, -1006, -1007])
async def test_unknown_execution_codes_raise_even_on_4xx(code):
    c, _ = client(resp(400, {"code": code, "msg": "Timeout waiting for response from backend server."}))
    with pytest.raises(ExchangeError, match=str(code)):
        await c.place_ioc(order())


@pytest.mark.parametrize("exc", [TimeoutError("timed out"),
                                 ConnectionResetError("reset by peer"), TransportError("URLError: dns")])
async def test_transport_failures_raise_exchange_error(exc):
    c, _ = client(exc)
    with pytest.raises(ExchangeError, match="state unknown"):
        await c.place_ioc(order())


@pytest.mark.parametrize("body", [b"not json", b"[]", json.dumps({"symbol": "BTCUSDT"}).encode()])
async def test_unparseable_2xx_raises_exchange_error(body):
    c, _ = client(HttpResponse(200, body))
    with pytest.raises(ExchangeError, match="unknown"):
        await c.place_ioc(order())


async def test_non_terminal_ioc_status_raises_for_reconciliation():
    c, _ = client(resp(200, full_response("NEW")))
    with pytest.raises(ExchangeError, match="still NEW"):
        await c.place_ioc(order())


async def test_response_for_another_order_raises():
    c, _ = client(resp(200, full_response("FILLED", cid="someone-else", executed="0.00200000", cumm="60")))
    with pytest.raises(ExchangeError, match="someone-else"):
        await c.place_ioc(order())


# --------------------------------------------------------------------------- local validation


@pytest.mark.parametrize("req, why", [
    (order(cid="arb:1"), "client id"),
    (order(cid="x" * 37), "client id"),
    (order(cid=""), "client id"),
    (order(tif="GTC"), "IOC"),
    (order(venue="bybit"), "venue"),
    (order(symbol="ETH-USDT"), "not configured"),
    (order(qty=0.0), "positive"),
    (order(limit=float("nan")), "positive"),
    (order(qty=0.000001), "zero on the venue grid"),  # below one lot (0.00001)
])
async def test_invalid_orders_are_rejected_without_sending(req, why):
    c, t = client()
    r = await c.place_ioc(req)
    assert r.status is OrderStatus.REJECTED and why in r.error
    assert t.requests == []


async def test_client_id_at_max_length_is_sent():
    cid = "A-b_9" * 7 + "z"  # 36 chars from the allowed set
    c, t = client(resp(200, full_response("EXPIRED", cid=cid)))
    r = await c.place_ioc(order(cid=cid))
    assert r.status is OrderStatus.EXPIRED
    assert dict(query_params(t.requests[0]))["newClientOrderId"] == cid


# --------------------------------------------------------------------------- query order


async def test_query_found_by_orig_client_order_id_estimates_fee():
    body = full_response("EXPIRED", executed="0.00100000", cumm="30.00000000")
    del body["fills"]  # GET /api/v3/order carries no fills
    c, t = client(resp(200, body))
    r = await c.query_order(order())
    (req,) = t.requests
    qs = "symbol=BTCUSDT&origClientOrderId=arb-1&recvWindow=5000&timestamp=1499827319559"
    expected_sig = hmac.new(DOC_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
    assert req.method == "GET"
    assert req.url == f"{TESTNET_URL}/api/v3/order?{qs}&signature={expected_sig}"
    assert dict(req.headers) == {API_KEY_HEADER: DOC_API_KEY}
    assert r is not None and r.status is OrderStatus.PARTIALLY_FILLED
    assert r.filled_qty == 0.001 and r.avg_price == 30000.0
    assert r.fee == 0.03  # 30 USDT * 10 bps, estimated
    assert any("fee estimated as 0.03 USDT" in n for n in c.notes_for("arb-1"))


async def test_query_filled():
    body = full_response("FILLED", executed="0.00200000", cumm="60.02000000")
    del body["fills"]
    c, _ = client(resp(200, body))
    r = await c.query_order(order())
    assert r.status is OrderStatus.FILLED and r.avg_price == 30010.0 and r.fee == 0.06002


async def test_query_not_found_returns_none():
    c, _ = client(resp(400, {"code": -2013, "msg": "Order does not exist."}))
    assert await c.query_order(order()) is None


async def test_query_archived_means_expired_without_fill():
    c, _ = client(resp(400, {"code": -2026, "msg": "Order was canceled or expired with no executed qty "
                                                   "over 90 days ago and has been archived."}))
    r = await c.query_order(order())
    assert r.status is OrderStatus.EXPIRED and r.filled_qty == 0.0


async def test_query_still_working_reports_unknown():
    body = full_response("PARTIALLY_FILLED", executed="0.00100000", cumm="30.00000000")
    c, _ = client(resp(200, body))
    r = await c.query_order(order())
    assert r.status is OrderStatus.UNKNOWN and r.filled_qty == 0.001 and "PARTIALLY_FILLED" in r.error


@pytest.mark.parametrize("response", [
    resp(400, {"code": -1021, "msg": "Timestamp for this request is outside of the recvWindow."}),
    resp(429, {"code": -1003, "msg": "Too many requests"}),
    resp(503, b""),
    TimeoutError("timed out"),
])
async def test_query_failures_raise_instead_of_guessing(response):
    c, _ = client(response)
    with pytest.raises(ExchangeError):
        await c.query_order(order())


async def test_query_for_unsendable_order_is_none_without_request():
    c, t = client()
    assert await c.query_order(order(cid="bad id")) is None
    assert t.requests == []


# --------------------------------------------------------------------------- decimal formatting


@pytest.mark.parametrize("x, s", [(1e-05, "0.00001"), (1e-08, "0.00000001"), (1e16, "10000000000000000"),
                                  (30000.0, "30000"), (0.1, "0.1"), (123.456, "123.456"), (5000, "5000"),
                                  ("2500.500", "2500.5")])
def test_format_decimal_never_uses_exponents(x, s):
    assert format_decimal(x) == s


async def test_tiny_values_are_sent_as_plain_decimals():
    c, t = client(resp(200, full_response("EXPIRED", symbol="DOGEBTC", orig="0.00001000")))
    await c.place_ioc(order(qty=1e-05, limit=2.5e-06, symbol="DOGE-BTC"))
    params = dict(query_params(t.requests[0]))
    assert params["quantity"] == "0.00001" and params["price"] == "0.0000025"
    assert "e" not in params["quantity"].lower() and "e" not in params["price"].lower()


async def test_float_noise_is_snapped_to_grid_never_more_aggressive():
    c, t = client(resp(200, full_response("EXPIRED", orig="0.30000000")),
                  resp(200, full_response("EXPIRED", side="SELL", orig="0.30000000", cid="arb-2")))
    await c.place_ioc(order(qty=0.1 + 0.2, limit=30000.004999))
    await c.place_ioc(order(Side.SELL, qty=0.1 + 0.2, limit=30000.001, cid="arb-2"))
    buy, sell = (dict(query_params(r)) for r in t.requests)
    assert (buy["quantity"], buy["price"]) == ("0.3", "30000")  # BUY limit rounds down
    assert (sell["quantity"], sell["price"]) == ("0.3", "30000.01")  # SELL limit rounds up


# --------------------------------------------------------------------------- mainnet guard


def test_testnet_is_default():
    c, _ = client()
    assert c.is_testnet and c.base_url == TESTNET_URL


@pytest.mark.parametrize("url", [MAINNET_URL, "https://api1.binance.com", "https://api-gcp.binance.com"])
def test_mainnet_requires_explicit_opt_in(url):
    with pytest.raises(ValueError, match="allow_mainnet"):
        BinanceSpotClient(venue_cfg(), DOC_API_KEY, DOC_SECRET, base_url=url, transport=FakeTransport())
    c = BinanceSpotClient(venue_cfg(), DOC_API_KEY, DOC_SECRET, base_url=url, allow_mainnet=True,
                          transport=FakeTransport())
    assert not c.is_testnet and "MAINNET" in repr(c)


async def test_mainnet_orders_go_to_mainnet_host():
    t = FakeTransport(resp(200, full_response("EXPIRED")))
    c = BinanceSpotClient(venue_cfg(), DOC_API_KEY, DOC_SECRET, base_url=MAINNET_URL, allow_mainnet=True,
                          transport=t, clock=SimClock(T_S))
    await c.place_ioc(order())
    assert t.requests[0].url.startswith("https://api.binance.com/api/v3/order?")


@pytest.mark.parametrize("kw", [{"base_url": "http://testnet.binance.vision"},
                                {"base_url": "https://testnet.binance.vision/api"},
                                {"recv_window_ms": 60001}, {"recv_window_ms": 0}])
def test_bad_construction_is_refused(kw):
    with pytest.raises(ValueError):
        BinanceSpotClient(venue_cfg(), DOC_API_KEY, DOC_SECRET, transport=FakeTransport(), **kw)


def test_missing_credentials_are_refused():
    with pytest.raises(ValueError):
        BinanceSpotClient(venue_cfg(), "", DOC_SECRET, transport=FakeTransport())
    with pytest.raises(ValueError):
        BinanceSpotClient(venue_cfg(), DOC_API_KEY, "", transport=FakeTransport())


# --------------------------------------------------------------------------- credential hygiene


def _leaks(text: str) -> bool:
    return DOC_API_KEY in text or DOC_SECRET in text


def test_credentials_never_in_repr_or_str():
    c, _ = client()
    for text in (repr(c), str(c), repr(vars(c)), str(vars(c))):
        assert not _leaks(text)
    req = HttpRequest("POST", f"{TESTNET_URL}/api/v3/order?a=1", {API_KEY_HEADER: DOC_API_KEY})
    assert not _leaks(repr(req)) and not _leaks(str(req))


async def test_credentials_never_in_exceptions_errors_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    c, _ = client(
        OSError(f"proxy said no to key {DOC_API_KEY} / {DOC_SECRET}"),
        resp(400, {"code": -2015, "msg": f"Invalid API-key {DOC_API_KEY}, IP, or permissions for action."}),
        resp(503, {"code": -1001, "msg": f"echo {DOC_SECRET}"}),
    )
    with pytest.raises(ExchangeError) as ei:
        await c.place_ioc(order())
    assert not _leaks(str(ei.value)) and ei.value.__cause__ is None and ei.value.__suppress_context__
    r = await c.place_ioc(order())
    assert r.status is OrderStatus.REJECTED and "-2015" in r.error and not _leaks(r.error)
    with pytest.raises(ExchangeError) as ei:
        await c.query_order(order())
    assert not _leaks(str(ei.value))
    assert not any(_leaks(rec.getMessage()) for rec in caplog.records)


# --------------------------------------------------------------------------- stdlib transport


class _Handler(BaseHTTPRequestHandler):
    seen: ClassVar[list[tuple[str, str, str | None, bytes]]] = []

    def _reply(self, status: int, body: bytes) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the /slow client already timed out and hung up, as the test intends

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        _Handler.seen.append((self.command, self.path, self.headers.get(API_KEY_HEADER), body))
        if self.path.startswith("/slow"):
            time.sleep(0.5)
        if self.path.startswith("/err"):
            self._reply(400, b'{"code":-2013,"msg":"Order does not exist."}')
        else:
            self._reply(200, b'{"ok":true}')

    do_GET = do_POST = _handle

    def log_message(self, *args) -> None:  # keep test output quiet
        pass


@pytest.fixture
def local_server() -> Iterator[str]:
    _Handler.seen = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


def _no_proxy_transport(timeout_s: float) -> UrllibTransport:
    return UrllibTransport(timeout_s, opener=urllib.request.build_opener(urllib.request.ProxyHandler({})))


async def test_urllib_transport_returns_every_status_and_sends_headers(local_server):
    t = _no_proxy_transport(2.0)
    ok = await t(HttpRequest("POST", f"{local_server}/api/v3/order?x=1", {API_KEY_HEADER: "k"}))
    err = await t(HttpRequest("GET", f"{local_server}/err?y=2", {API_KEY_HEADER: "k"}))
    assert ok == HttpResponse(200, b'{"ok":true}')
    assert err == HttpResponse(400, b'{"code":-2013,"msg":"Order does not exist."}')
    assert _Handler.seen == [("POST", "/api/v3/order?x=1", "k", b""), ("GET", "/err?y=2", "k", b"")]


async def test_urllib_transport_timeout_and_refused_raise_transport_error(local_server):
    with pytest.raises(TransportError):
        await _no_proxy_transport(0.1)(HttpRequest("GET", f"{local_server}/slow", {}))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    srv.server_close()  # nothing listens on this port any more
    with pytest.raises(TransportError):
        await _no_proxy_transport(1.0)(HttpRequest("GET", f"http://127.0.0.1:{port}/", {}))


# --------------------------------------------------------------------------- review findings (regressions)


async def test_buy_commission_in_base_is_reported_as_base_fee():
    fills = [
        fill("30000.00000000", "0.00120000", "0.00000120", "BTC"),
        fill("30005.00000000", "0.00080000", "0.02400400", "USDT", 57),
    ]
    body = full_response("FILLED", executed="0.00200000", cumm="60.00400000", fills=fills)
    c, _ = client(resp(200, body))
    r = await c.place_ioc(order())
    assert r.filled_qty == 0.002 and r.fee == 0.060004
    assert r.base_fee == 0.0000012  # the account received 0.0019988 BTC


async def test_reconciled_buy_assumes_the_commission_was_taken_in_base():
    body = full_response("FILLED", executed="0.00200000", cumm="60.02000000")
    del body["fills"]  # GET /api/v3/order: commission asset unknown
    c, _ = client(resp(200, body))
    r = await c.query_order(order())
    assert r.fee == 0.06002 and r.base_fee == pytest.approx(0.000002)
    assert any("assumed" in n and "BTC" in n for n in c.notes_for("arb-1"))
    sell_body = full_response("FILLED", side="SELL", executed="0.00200000", cumm="60.02000000")
    del sell_body["fills"]
    c2, _ = client(resp(200, sell_body))
    assert (await c2.query_order(order(Side.SELL))).base_fee == 0.0  # a SELL pays in quote


async def test_long_position_exit_sells_only_what_binance_credited():
    """Binance takes a BUY's commission from the base received: 1 BTC bought credits 0.999 BTC.

    The fake venue applies that rule and refuses (-2010) any SELL above the free balance. The position
    must be 0.999 so its stop exit is accepted; selling 1.0 would be refused at every attempt.
    """
    from urllib.parse import parse_qsl as _qsl

    from arbbot.config import BotConfig, ReferenceLagConfig
    from arbbot.execution.engine import ExecutionEngine
    from arbbot.execution.monitor import PositionMonitor
    from arbbot.feeds.base import QuoteBook
    from arbbot.models import Leg, Quote, Signal, SignalKind
    from arbbot.portfolio import Portfolio

    account = {"BTC": 0.0, "USDT": 10_000.0}
    sells: list[str] = []

    async def fake_binance(req: HttpRequest) -> HttpResponse:
        p = dict(_qsl(urlsplit(req.url).query))
        side, qty, px = p["side"], float(p["quantity"]), float(p["price"])
        if side == "SELL":
            sells.append(p["quantity"])
            if qty > account["BTC"] + 1e-12:
                return resp(400, {"code": -2010, "msg": "Account has insufficient balance for requested action."})
            commission, asset = qty * px * 0.001, "USDT"
            account["BTC"] -= qty
        else:
            commission, asset = qty * 0.001, "BTC"
            account["BTC"] += qty - commission
        body = full_response("FILLED", side=side, orig=p["quantity"], executed=p["quantity"],
                             cumm=f"{qty * px:.8f}", cid=p["newClientOrderId"], price=p["price"],
                             fills=[fill(p["price"], p["quantity"], f"{commission:.8f}", asset)])
        return resp(200, body)

    clock = SimClock(T_S)
    venue = venue_cfg()
    cfg = BotConfig(venues=(venue,), reference_lag=ReferenceLagConfig(
        enabled=True, reference_venue="binance", reference_symbol="BTC-USDT", target_venue="binance",
        target_symbol="BTC-USDT"))
    c = BinanceSpotClient(venue, DOC_API_KEY, DOC_SECRET, transport=fake_binance, clock=clock)
    pf = Portfolio({"binance": {"USDT": 10_000.0}})
    book = QuoteBook()
    book.update(Quote("binance", "BTC-USDT", 99.99, 10.0, 100.0, 10.0, clock.now()))
    engine = ExecutionEngine(cfg, {"binance": c}, pf, book, clock)
    monitor = PositionMonitor(cfg, engine, clock)
    sig = Signal("sig-1", SignalKind.REFERENCE_LAG, "BTC-USDT", "m", (Leg("binance", "BTC-USDT", Side.BUY, 100.0, 10.0),),
                 1.0, 30.0, 20.0, 10.0, 1.0, 100.0, 99.85, 100.2, clock.now(), max_hold_s=30.0)
    _, pos = await engine.enter(sig, 1.0)
    assert pos is not None and pos.qty == pytest.approx(0.999)
    assert pf.balance("binance", "BTC") == pytest.approx(0.999) == pytest.approx(account["BTC"])
    monitor.open(pos)
    clock.set(T_S + 1)
    (exit_rep,) = await monitor.on_quote(Quote("binance", "BTC-USDT", 99.5, 10.0, 99.51, 10.0, clock.now()))
    assert sells == ["0.999"] and exit_rep.outcome.value == "closed"
    assert monitor.positions == () and monitor.residuals == ()
    assert account["BTC"] == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("key", [DOC_API_KEY + "\n", DOC_API_KEY + " ", "\t" + DOC_API_KEY, "ab cd"])
def test_credentials_with_whitespace_are_refused_without_echoing_them(key):
    with pytest.raises(ValueError) as ei:
        BinanceSpotClient(venue_cfg(), key, DOC_SECRET, transport=FakeTransport())
    assert DOC_API_KEY not in str(ei.value) and "ab cd" not in str(ei.value)
    with pytest.raises(ValueError):
        BinanceSpotClient(venue_cfg(), DOC_API_KEY, DOC_SECRET + "\r\n", transport=FakeTransport())


async def test_foreign_transport_exception_text_never_reaches_errors(caplog):
    # http.client rejects an invalid header with ValueError(f"Invalid header value {value!r}"): the
    # repr-escaped key would slip past an exact-match scrub. Only the exception type is reported.
    caplog.set_level(logging.DEBUG)
    escaped = repr(DOC_API_KEY + "\n").encode()
    c, _ = client(ValueError(f"Invalid header value b{escaped.decode()}"), ValueError(f"oops {DOC_SECRET!r}"))
    with pytest.raises(ExchangeError) as ei:
        await c.place_ioc(order())
    assert "ValueError" in str(ei.value) and "Invalid header" not in str(ei.value) and not _leaks(str(ei.value))
    with pytest.raises(ExchangeError) as ei:
        await c.query_order(order())
    assert not _leaks(str(ei.value))
    assert not any(_leaks(r.getMessage()) for r in caplog.records)


def test_scrub_covers_escaped_and_stripped_forms():
    from arbbot.execution.binance_live import _Credentials

    creds = _Credentials("KEY1234\n", "SECRET99")
    text = "a KEY1234\\n b KEY1234 c 'SECRET99'"
    assert creds.scrub(text) == "a *** b *** c '***'"
