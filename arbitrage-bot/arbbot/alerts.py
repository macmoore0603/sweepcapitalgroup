"""Operator alerts: fire-and-forget webhook posts with a JSON ``{"text": ...}`` body.

The body is the shape Slack incoming webhooks accept (POST, ``Content-Type:
application/json``, ``{"text": "..."}``; Slack answers ``200 ok``). Alerts
must never slow down or break trading, so ``send`` only queues the text for a
background thread and returns; delivery failures are logged, never raised.

Each delivery has a hard total deadline of ``timeout_s``. ``urlopen``'s own
timeout applies per socket operation, so an endpoint (or proxy) that trickles
its response could otherwise hold the delivery thread forever and keep a later
kill-switch alert queued behind it; a POST past the deadline is abandoned
(counted as failed) and the next alert goes out. Alerts still undelivered when
``close`` gives up are logged at ERROR level, never dropped silently.

Payloads carry only what the bot composes (outcomes, reasons, signal ids,
markets), capped in length, with the values of the credential environment
variables scrubbed out in case one ever ends up in an error string. The
webhook URL is itself a secret (Slack's docs say so), so it is never logged:
log lines name only its host.

``alerter_from_env()`` returns a ``WebhookAlerter`` when ``ARBBOT_ALERT_WEBHOOK``
is set and a ``LogAlerter`` (log only) otherwise.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from typing import Protocol
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

ENV_WEBHOOK = "ARBBOT_ALERT_WEBHOOK"
# Values of these variables are scrubbed from every alert text.
SECRET_ENV_VARS = ("ARBBOT_BINANCE_API_KEY", "ARBBOT_BINANCE_API_SECRET", ENV_WEBHOOK)
MAX_TEXT_CHARS = 2000
_REDACTED = "***"
_MIN_SECRET_LEN = 4  # never "redact" a trivially short value that would mangle normal text

Post = Callable[[str, bytes, float], None]  # (url, json body, timeout seconds); raises on failure


class Alerter(Protocol):
    def send(self, text: str) -> None:
        """Deliver ``text`` without blocking the caller and without raising."""
        ...

    def close(self, timeout_s: float = 5.0) -> None:
        """Flush what is queued (bounded by ``timeout_s``) and stop."""
        ...


def redact(text: str, secrets: Iterable[str]) -> str:
    """``text`` with every occurrence of each secret (>= 4 chars) replaced by ``***``."""
    for s in sorted({s for s in secrets if s and len(s) >= _MIN_SECRET_LEN}, key=len, reverse=True):
        text = text.replace(s, _REDACTED)
    return text


def _clip(text: str) -> str:
    return text if len(text) <= MAX_TEXT_CHARS else text[: MAX_TEXT_CHARS - 1] + "…"


class NullAlerter:
    """Drops alerts (backtests)."""

    def send(self, text: str) -> None:
        pass

    def close(self, timeout_s: float = 5.0) -> None:
        pass


class LogAlerter:
    """Writes alerts to the log only (no webhook configured)."""

    def __init__(self, *, secrets: Iterable[str] = ()) -> None:
        self._secrets = tuple(secrets)

    def send(self, text: str) -> None:
        log.warning("ALERT: %s", _clip(redact(text, self._secrets)))

    def close(self, timeout_s: float = 5.0) -> None:
        pass


def urllib_post(url: str, body: bytes, timeout_s: float) -> None:
    """POST ``body`` as JSON; raises on network errors and non-2xx statuses."""
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # scheme checked in WebhookAlerter
        status = resp.status
    if not 200 <= status < 300:
        raise OSError(f"HTTP {status}")


_STOP = object()


class WebhookAlerter:
    """Posts ``{"text": ...}`` to a webhook from a daemon thread; ``send`` never blocks or raises.

    At most ``max_pending`` alerts wait in the queue; beyond that new ones are
    dropped (and logged) rather than blocking the caller. Each POST must finish
    within ``timeout_s`` in total or it is abandoned.
    """

    def __init__(
        self,
        url: str,
        *,
        timeout_s: float = 5.0,
        max_pending: int = 100,
        post: Post | None = None,
        secrets: Iterable[str] = (),
    ) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("https", "http") or not parts.hostname:
            raise ValueError(f"{ENV_WEBHOOK} must be an http(s) URL")  # the URL itself is not echoed
        if parts.scheme == "http":
            log.warning("alert webhook on %s uses plain http: its secret travels unencrypted", parts.hostname)
        if max_pending < 1:
            raise ValueError("max_pending must be >= 1")
        self.host = parts.hostname
        self._url = url
        self._timeout_s = timeout_s
        self._post = post or urllib_post
        self._secrets = (*secrets, url)
        self._queue: queue.Queue[object] = queue.Queue(max_pending)
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._closed = False
        self._current: bytes | None = None  # the alert being delivered right now
        self.sent = 0
        self.failed = 0
        self.dropped = 0

    def __repr__(self) -> str:
        return f"WebhookAlerter(host={self.host!r})"

    def send(self, text: str) -> None:
        try:
            text = _clip(redact(str(text), self._secrets))
            log.warning("ALERT: %s", text)
            if self._closed:
                self.dropped += 1
                return
            self._ensure_thread()
            self._queue.put_nowait(json.dumps({"text": text}).encode("utf-8"))
        except queue.Full:
            self.dropped += 1
            log.error("alert queue full (%d pending): alert dropped", self._queue.maxsize)
        except Exception as e:  # noqa: BLE001 - an alert must never take the bot down
            self.dropped += 1
            log.error("could not queue alert: %s", type(e).__name__)

    def close(self, timeout_s: float = 5.0) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            thread = self._thread
        if thread is None:
            return
        try:
            self._queue.put(_STOP, timeout=timeout_s)
        except queue.Full:
            log.error("alert queue still full at shutdown; pending alerts dropped")
            return
        thread.join(timeout_s)
        if thread.is_alive():
            log.error("alert delivery still running after %.1fs at shutdown", timeout_s)
            self._log_undelivered()

    def _log_undelivered(self) -> None:
        """At shutdown: log every alert that will not be delivered, so none is lost silently."""
        pending = [self._current] if self._current is not None else []
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, bytes):
                pending.append(item)
        for item in pending:
            self.dropped += 1
            try:
                text = json.loads(item)["text"]
            except (ValueError, KeyError, TypeError):
                text = "?"
            log.error("alert NOT delivered to %s before shutdown: %s", self.host, text)
        try:
            self._queue.put_nowait(_STOP)  # the worker exits after its current delivery
        except queue.Full:
            pass

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._worker, name="arbbot-alerts", daemon=True)
                self._thread.start()

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            assert isinstance(item, bytes)
            self._current = item
            try:
                self._deliver(item)
            finally:
                self._current = None

    def _deliver(self, item: bytes) -> None:
        """One POST with a hard total deadline of ``timeout_s``; past it the POST is abandoned."""
        done = threading.Event()
        errors: list[Exception] = []

        def post() -> None:
            try:
                self._post(self._url, item, self._timeout_s)
            except Exception as e:  # noqa: BLE001 - delivery failures are logged, never raised
                errors.append(e)
            finally:
                done.set()

        threading.Thread(target=post, name="arbbot-alert-post", daemon=True).start()
        if not done.wait(self._timeout_s):
            self.failed += 1
            log.warning("alert delivery to %s took longer than %.1fs in total: abandoned", self.host,
                        self._timeout_s)
            return
        if errors:
            self.failed += 1
            why = redact(f"{type(errors[0]).__name__}: {errors[0]}", self._secrets)
            log.warning("alert delivery to %s failed: %s", self.host, why)
        else:
            self.sent += 1


def alerter_from_env(env: Mapping[str, str] | None = None, *, post: Post | None = None) -> Alerter:
    """``WebhookAlerter`` if ``ARBBOT_ALERT_WEBHOOK`` is set, else ``LogAlerter``."""
    env = os.environ if env is None else env
    # Both the raw and the stripped value: the bot uses credentials stripped of a trailing newline.
    secrets = [v for k in SECRET_ENV_VARS if env.get(k) for v in {env[k], env[k].strip()}]
    url = env.get(ENV_WEBHOOK, "").strip()
    if not url:
        return LogAlerter(secrets=secrets)
    return WebhookAlerter(url, post=post, secrets=secrets)
