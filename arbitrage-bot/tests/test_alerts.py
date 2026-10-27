"""Tests for arbbot.alerts: JSON {"text": ...} webhook posts that never block or raise, with no secrets."""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from arbbot.alerts import (
    ENV_WEBHOOK,
    MAX_TEXT_CHARS,
    LogAlerter,
    NullAlerter,
    WebhookAlerter,
    alerter_from_env,
    redact,
)


class Received:
    def __init__(self) -> None:
        self.posts: list[tuple[str, str, bytes]] = []  # (path, content-type, body)
        self.event = threading.Event()


@pytest.fixture
def server():
    received = Received()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.posts.append((self.path, self.headers["Content-Type"], body))
            status = 500 if self.path.endswith("/fail") else 200
            self.send_response(status)
            self.end_headers()
            self.wfile.write(b"ok")
            received.event.set()

        def log_message(self, *args: object) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", received
    httpd.shutdown()
    httpd.server_close()


def test_posts_json_text_to_the_webhook(server) -> None:
    base, received = server
    alerter = WebhookAlerter(f"{base}/services/T000/B000/XXXXSECRETTOKEN")
    alerter.send("kill switch tripped: residual")
    alerter.close(timeout_s=5.0)
    assert received.posts == [
        ("/services/T000/B000/XXXXSECRETTOKEN", "application/json",
         json.dumps({"text": "kill switch tripped: residual"}).encode()),
    ]
    assert (alerter.sent, alerter.failed, alerter.dropped) == (1, 0, 0)


def test_http_errors_are_logged_without_the_url_and_never_raised(server, caplog) -> None:
    base, received = server
    url = f"{base}/hooks/SUPERSECRETTOKEN/fail"
    alerter = WebhookAlerter(url)
    with caplog.at_level(logging.WARNING, logger="arbbot.alerts"):
        alerter.send("hello")
        alerter.close(timeout_s=5.0)
    assert len(received.posts) == 1
    assert (alerter.sent, alerter.failed) == (0, 1)
    assert "alert delivery to 127.0.0.1 failed" in caplog.text
    assert "SUPERSECRETTOKEN" not in caplog.text


def test_connection_failure_is_logged_not_raised(caplog) -> None:
    def refuse(url: str, body: bytes, timeout: float) -> None:
        raise ConnectionRefusedError(f"cannot reach {url}")

    alerter = WebhookAlerter("https://hooks.example.com/services/TOKEN123", post=refuse)
    with caplog.at_level(logging.WARNING, logger="arbbot.alerts"):
        alerter.send("x")
        alerter.close(timeout_s=5.0)
    assert alerter.failed == 1
    assert "ConnectionRefusedError" in caplog.text
    assert "TOKEN123" not in caplog.text and "cannot reach ***" in caplog.text


def test_send_never_blocks_and_drops_when_the_queue_is_full() -> None:
    release = threading.Event()
    delivered: list[bytes] = []

    def slow_post(url: str, body: bytes, timeout: float) -> None:
        release.wait(5.0)
        delivered.append(body)

    alerter = WebhookAlerter("https://hooks.example.com/x", post=slow_post, max_pending=1)
    t0 = time.monotonic()
    alerter.send("one")  # taken by the worker, which then blocks in slow_post
    deadline = time.monotonic() + 5.0
    while alerter._queue.qsize() and time.monotonic() < deadline:  # wait until the worker took it
        time.sleep(0.001)
    alerter.send("two")  # waits in the queue
    alerter.send("three")  # queue full: dropped
    assert time.monotonic() - t0 < 1.0  # none of the sends waited for delivery
    assert alerter.dropped == 1
    release.set()
    alerter.close(timeout_s=5.0)
    assert [json.loads(b)["text"] for b in delivered] == ["one", "two"]
    alerter.send("after close")  # closed: dropped quietly
    assert alerter.dropped == 2


def test_secrets_from_env_never_reach_the_payload() -> None:
    bodies: list[bytes] = []
    env = {
        ENV_WEBHOOK: "https://hooks.example.com/services/WEBHOOKSECRET",
        "ARBBOT_BINANCE_API_KEY": "my-api-key-value",
        "ARBBOT_BINANCE_API_SECRET": "my-api-secret-value",
    }
    alerter = alerter_from_env(env, post=lambda url, body, timeout: bodies.append(body))
    assert isinstance(alerter, WebhookAlerter) and alerter.host == "hooks.example.com"
    assert "WEBHOOKSECRET" not in repr(alerter)
    alerter.send("error: key=my-api-key-value secret=my-api-secret-value at "
                 "https://hooks.example.com/services/WEBHOOKSECRET")
    alerter.close(timeout_s=5.0)
    (body,) = bodies
    assert json.loads(body) == {"text": "error: key=*** secret=*** at ***"}


def test_long_texts_are_clipped() -> None:
    bodies: list[bytes] = []
    alerter = WebhookAlerter("https://hooks.example.com/x", post=lambda u, b, t: bodies.append(b))
    alerter.send("x" * (MAX_TEXT_CHARS + 50))
    alerter.close(timeout_s=5.0)
    text = json.loads(bodies[0])["text"]
    assert len(text) == MAX_TEXT_CHARS and text.endswith("…")


def test_from_env_without_webhook_logs_only(caplog) -> None:
    alerter = alerter_from_env({"ARBBOT_BINANCE_API_SECRET": "topsecret-value"})
    assert isinstance(alerter, LogAlerter)
    with caplog.at_level(logging.WARNING, logger="arbbot.alerts"):
        alerter.send("leak topsecret-value?")
    assert "ALERT: leak ***?" in caplog.text
    NullAlerter().send("ignored")


def test_bad_webhook_url_is_rejected_without_echoing_it() -> None:
    with pytest.raises(ValueError) as e:
        WebhookAlerter("ftp://hooks.example.com/SECRETPATH")
    assert "SECRETPATH" not in str(e.value)


def test_redact() -> None:
    assert redact("a abcd b abcdef", ["abcd", "abcdef"]) == "a *** b ***"  # longest first
    assert redact("short ab", ["ab", ""]) == "short ab"  # < 4 chars is never treated as a secret


# --------------------------------------------------------------------------- review findings (regressions)


def _wait_until(cond, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while not cond():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def test_a_slow_delivery_is_abandoned_so_a_later_kill_switch_alert_still_goes_out() -> None:
    stuck = threading.Event()  # never set while the test runs: the first POST hangs
    delivered: list[str] = []

    def post(url: str, body: bytes, timeout: float) -> None:
        text = json.loads(body)["text"]
        if text == "feed blip":
            stuck.wait(30.0)
        delivered.append(text)

    alerter = WebhookAlerter("https://hooks.example.com/x", timeout_s=0.2, post=post)
    try:
        alerter.send("feed blip")
        alerter.send("kill switch tripped: residual")
        assert _wait_until(lambda: "kill switch tripped: residual" in delivered, 3.0)
        assert (alerter.sent, alerter.failed) == (1, 1)
    finally:
        stuck.set()
        alerter.close(timeout_s=2.0)


def test_a_webhook_that_trickles_its_response_cannot_stall_delivery(monkeypatch) -> None:
    """The real urllib POST: its timeout is per socket read, and this endpoint sends a byte every 0.3 s."""
    for var in ("http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    bodies: list[bytes] = []

    def handle(conn: socket.socket) -> None:
        with conn:
            data = b""
            while b"\r\n\r\n" not in data:
                data += conn.recv(65536)
            head, _, body = data.partition(b"\r\n\r\n")
            length = int(next(line.split(b":")[1] for line in head.split(b"\r\n")
                              if line.lower().startswith(b"content-length")))
            while len(body) < length:
                body += conn.recv(65536)
            bodies.append(body)
            for b in b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok":
                time.sleep(0.3)
                try:
                    conn.send(bytes([b]))
                except OSError:
                    return

    def serve() -> None:
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=handle, args=(conn,), daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()
    alerter = WebhookAlerter(f"http://127.0.0.1:{srv.getsockname()[1]}/hook", timeout_s=0.5)
    try:
        alerter.send("first alert")
        alerter.send("kill switch tripped: residual")
        assert _wait_until(lambda: any(b"kill switch" in b for b in bodies), 4.0)
    finally:
        alerter.close(timeout_s=1.0)
        srv.close()


def test_close_logs_every_alert_it_could_not_deliver(caplog) -> None:
    stuck = threading.Event()

    def post(url: str, body: bytes, timeout: float) -> None:
        stuck.wait(30.0)

    alerter = WebhookAlerter("https://hooks.example.com/x", timeout_s=5.0, post=post)
    try:
        for text in ("one", "two", "three"):
            alerter.send(text)
        assert _wait_until(lambda: alerter._queue.qsize() == 2)  # "one" is being delivered
        with caplog.at_level(logging.ERROR, logger="arbbot.alerts"):
            alerter.close(timeout_s=0.1)
        lost = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR and "NOT delivered" in r.getMessage()]
        assert [m.rsplit(": ", 1)[1] for m in lost] == ["one", "two", "three"]
        assert alerter.dropped == 3
    finally:
        stuck.set()


def test_from_env_also_redacts_the_stripped_credential(caplog) -> None:
    # A key read from a secret file ends in a newline; the bot uses it stripped.
    alerter = alerter_from_env({"ARBBOT_BINANCE_API_KEY": "my-api-key-value\n"})
    with caplog.at_level(logging.WARNING, logger="arbbot.alerts"):
        alerter.send("rejected key my-api-key-value")
    assert "my-api-key-value" not in caplog.text and "rejected key ***" in caplog.text
