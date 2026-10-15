"""Unit tests for EdgeGuard and GuardMiddleware (no ScyllaDB)."""

from __future__ import annotations

import asyncio
import json
import time

from core.guard import EdgeGuard, GuardPolicy
from core.guard_middleware import GuardMiddleware


class FakeCounter:
    """HitCounter stand-in recording every bucket call."""

    def __init__(self, fail: Exception | None = None) -> None:
        self.calls: list[tuple[str, int]] = []
        self._hits = 0
        self._fail = fail

    def __call__(self, bucket: str, window_seconds: int) -> int:
        self.calls.append((bucket, window_seconds))
        if self._fail is not None:
            raise self._fail
        self._hits += 1
        return self._hits


async def _ok_app(scope, receive, send) -> None:
    await send(
        {"type": "http.response.start", "status": 200, "headers": []}
    )
    await send({"type": "http.response.body", "body": b"{}"})


async def _dispatch(
    middleware: GuardMiddleware,
    *,
    path: str = "/items",
    headers: list[tuple[bytes, bytes]] | None = None,
    peer: str = "203.0.113.7",
) -> list[dict]:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers or [],
        "client": (peer, 40000),
    }
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    await middleware(scope, receive, send)
    return sent


def _body(sent: list[dict]) -> dict:
    return json.loads(sent[1]["body"])


def _headers(sent: list[dict]) -> dict[bytes, bytes]:
    return dict(sent[0]["headers"])


def test_policy_from_settings_defaults() -> None:
    from core.config import Settings

    policy = GuardPolicy.from_settings(Settings(jwt_secret="x" * 32))
    assert policy.enabled is True
    assert policy.max_concurrent == 256
    assert policy.ip_max_hits == 300
    assert policy.max_body_bytes == 128 * 1024 * 1024
    assert "/health" in policy.exempt_paths
    assert policy.client_ip_header == "cf-connecting-ip"


def test_exempt_paths_and_extra_exempt() -> None:
    guard = EdgeGuard(GuardPolicy(), FakeCounter())
    for path in ("/health", "/ready", "/docs", "/openapi.json"):
        assert guard.is_exempt(path)
    assert not guard.is_exempt("/posts")
    wide = EdgeGuard(
        GuardPolicy(exempt_paths=frozenset({"/health", "/metrics"})),
        FakeCounter(),
    )
    assert wide.is_exempt("/metrics")


def test_body_allowed_content_length() -> None:
    guard = EdgeGuard(GuardPolicy(max_body_bytes=10), FakeCounter())
    assert guard.body_allowed({}) is True
    assert guard.body_allowed({"content-length": "10"}) is True
    assert guard.body_allowed({"content-length": "11"}) is False
    assert guard.body_allowed({"content-length": "chunked"}) is True


def test_client_ip_header_first_hop_then_peer() -> None:
    guard = EdgeGuard(GuardPolicy(), FakeCounter())
    assert (
        guard.client_ip({"cf-connecting-ip": "9.9.9.9"}, "1.1.1.1")
        == "9.9.9.9"
    )
    assert (
        guard.client_ip({"cf-connecting-ip": "9.9.9.9, 8.8.8.8"}, "1.1.1.1")
        == "9.9.9.9"
    )
    assert guard.client_ip({}, "1.1.1.1") == "1.1.1.1"
    assert guard.client_ip({}, None) == "unknown"


def test_client_ip_peer_when_header_disabled() -> None:
    guard = EdgeGuard(GuardPolicy(client_ip_header=""), FakeCounter())
    assert (
        guard.client_ip({"cf-connecting-ip": "9.9.9.9"}, "1.1.1.1")
        == "1.1.1.1"
    )


async def test_check_ip_counts_then_suppresses() -> None:
    counter = FakeCounter()
    guard = EdgeGuard(
        GuardPolicy(ip_max_hits=2, ip_window_seconds=60), counter
    )
    assert await guard.check_ip("1.2.3.4") == 0.0
    assert await guard.check_ip("1.2.3.4") == 0.0
    retry = await guard.check_ip("1.2.3.4")
    assert retry >= 1
    assert counter.calls == [("edge:1.2.3.4", 60)] * 3
    assert guard.suppressed_retry("1.2.3.4") > 0
    assert guard.suppressed_retry("5.6.7.8") == 0.0


async def test_check_ip_fails_open_on_counter_error() -> None:
    guard = EdgeGuard(
        GuardPolicy(ip_max_hits=1), FakeCounter(fail=RuntimeError("db"))
    )
    assert await guard.check_ip("1.2.3.4") == 0.0


def test_suppression_expires() -> None:
    guard = EdgeGuard(GuardPolicy(), FakeCounter())
    guard._suppressed["1.2.3.4"] = time.monotonic() - 1
    assert guard.suppressed_retry("1.2.3.4") == 0.0
    assert "1.2.3.4" not in guard._suppressed


async def test_slot_sheds_when_full() -> None:
    guard = EdgeGuard(
        GuardPolicy(max_concurrent=1, queue_ms=0), FakeCounter()
    )
    assert await guard.acquire_slot() is True
    assert await guard.acquire_slot() is False
    guard.release_slot()
    assert await guard.acquire_slot() is True


async def test_slot_queue_wakes_oldest_on_release() -> None:
    guard = EdgeGuard(
        GuardPolicy(max_concurrent=1, queue_ms=1000), FakeCounter()
    )
    assert await guard.acquire_slot() is True
    waiter = asyncio.create_task(guard.acquire_slot())
    await asyncio.sleep(0.01)
    guard.release_slot()
    assert await waiter is True


async def test_slot_queue_timeout_sheds() -> None:
    guard = EdgeGuard(
        GuardPolicy(max_concurrent=1, queue_ms=30), FakeCounter()
    )
    assert await guard.acquire_slot() is True
    assert await guard.acquire_slot() is False


async def test_middleware_passes_clean_request() -> None:
    mw = GuardMiddleware(_ok_app, guard=EdgeGuard(GuardPolicy(), FakeCounter()))
    sent = await _dispatch(mw)
    assert sent[0]["status"] == 200


async def test_middleware_rejects_oversized_body() -> None:
    mw = GuardMiddleware(
        _ok_app,
        guard=EdgeGuard(GuardPolicy(max_body_bytes=10), FakeCounter()),
    )
    sent = await _dispatch(mw, headers=[(b"content-length", b"999")])
    assert sent[0]["status"] == 413
    assert _body(sent) == {
        "code": "MEDIA_TOO_LARGE",
        "message": "Request body too large.",
    }


async def test_middleware_429_then_suppressed() -> None:
    counter = FakeCounter()
    mw = GuardMiddleware(
        _ok_app,
        guard=EdgeGuard(GuardPolicy(ip_max_hits=1), counter),
    )
    assert (await _dispatch(mw))[0]["status"] == 200
    blocked = await _dispatch(mw)
    assert blocked[0]["status"] == 429
    assert _body(blocked)["code"] == "TOO_MANY_REQUESTS"
    assert int(_headers(blocked)[b"retry-after"]) >= 1
    assert (await _dispatch(mw))[0]["status"] == 429
    # Suppressed flood requests never reach the counter again.
    assert len(counter.calls) == 2


async def test_middleware_503_when_saturated() -> None:
    guard = EdgeGuard(GuardPolicy(max_concurrent=1, queue_ms=0), FakeCounter())
    mw = GuardMiddleware(_ok_app, guard=guard)
    assert await guard.acquire_slot() is True
    sent = await _dispatch(mw)
    assert sent[0]["status"] == 503
    assert _body(sent)["code"] == "SERVER_OVERLOADED"
    assert _headers(sent)[b"retry-after"] == b"1"
    guard.release_slot()
    assert (await _dispatch(mw))[0]["status"] == 200


async def test_middleware_skips_websocket_and_exempt() -> None:
    called: list[str] = []

    async def app(scope, receive, send) -> None:
        called.append(scope["type"])
        if scope["type"] == "http":
            await _ok_app(scope, receive, send)

    mw = GuardMiddleware(app, guard=EdgeGuard(GuardPolicy(), FakeCounter()))

    async def receive() -> dict:
        return {"type": "websocket.connect"}

    async def send(message: dict) -> None:
        pass

    await mw(
        {"type": "websocket", "path": "/ws", "headers": []},
        receive,
        send,
    )
    assert called == ["websocket"]
    assert (await _dispatch(mw, path="/health"))[0]["status"] == 200


async def test_middleware_disabled_passes_through() -> None:
    mw = GuardMiddleware(
        _ok_app,
        guard=EdgeGuard(GuardPolicy(enabled=False), FakeCounter()),
    )
    assert (await _dispatch(mw))[0]["status"] == 200
