"""Regression locks: edge guard envelope shape and exempt-path contract."""

from __future__ import annotations

import json

from httpx import AsyncClient

from core.guard import EdgeGuard, GuardPolicy
from core.guard_middleware import GuardMiddleware


async def _downstream(scope, receive, send) -> None:
    await send(
        {"type": "http.response.start", "status": 200, "headers": []}
    )
    await send({"type": "http.response.body", "body": b"{}"})


async def _call(middleware: GuardMiddleware, path: str = "/posts") -> list:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "client": ("203.0.113.7", 40000),
    }
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    await middleware(scope, receive, send)
    return sent


async def test_overload_envelope_and_retry_after() -> None:
    """503 stays {code, message} + Retry-After (SERVER_OVERLOADED)."""
    guard = EdgeGuard(
        GuardPolicy(max_concurrent=1, queue_ms=0), lambda bucket, window: 1
    )
    middleware = GuardMiddleware(_downstream, guard=guard)
    assert await guard.acquire_slot() is True
    sent = await _call(middleware)
    guard.release_slot()
    assert sent[0]["status"] == 503
    assert dict(sent[0]["headers"])[b"retry-after"] == b"1"
    assert json.loads(sent[1]["body"]) == {
        "code": "SERVER_OVERLOADED",
        "message": "Server is overloaded. Try again shortly.",
    }


async def test_rate_limit_envelope_frozen(client: AsyncClient) -> None:
    """429 keeps the shared error envelope plus a Retry-After hint."""
    import main

    from core.config import get_settings
    from tests.conftest import _test_settings

    main.app.dependency_overrides[get_settings] = lambda: (
        _test_settings().model_copy(update={"guard_ip_max_hits": 1})
    )
    assert (await client.get("/")).status_code == 200
    blocked = await client.get("/")
    assert blocked.status_code == 429
    assert set(blocked.json()) == {"code", "message"}
    assert blocked.json()["code"] == "TOO_MANY_REQUESTS"
    assert int(blocked.headers["retry-after"]) >= 1


async def test_exempt_probe_contract(client: AsyncClient) -> None:
    """Probes and docs stay reachable even past a one-hit limit."""
    import main

    from core.config import get_settings
    from tests.conftest import _test_settings

    main.app.dependency_overrides[get_settings] = lambda: (
        _test_settings().model_copy(update={"guard_ip_max_hits": 1})
    )
    assert (await client.get("/")).status_code == 200
    for path in ("/health", "/docs", "/openapi.json"):
        assert (await client.get(path)).status_code == 200
