"""Pure-ASGI middleware wiring the EdgeGuard into every HTTP request."""

from __future__ import annotations

import json
import logging
import math
from typing import TYPE_CHECKING, Any

from core.config import get_settings
from core.guard import EdgeGuard, GuardPolicy

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from core.config import Settings

    Scope = dict[str, Any]
    Message = dict[str, Any]
    Receive = Callable[[], Awaitable[Message]]
    Send = Callable[[Message], Awaitable[None]]

logger = logging.getLogger("amigoact.guard")

_GUARD_CACHE_LIMIT = 16


class GuardMiddleware:
    """Second wall: sheds load at the edge before it reaches routes.

    `guard` may be injected (tests); otherwise one EdgeGuard is built
    per resolved settings signature through core.dependencies.
    """

    def __init__(self, app, guard: EdgeGuard | None = None) -> None:
        self._app = app
        self._fixed_guard = guard
        self._guards: dict[tuple, EdgeGuard] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        guard = self._guard_for(scope)
        if not guard.policy.enabled or guard.is_exempt(scope.get("path", "")):
            await self._app(scope, receive, send)
            return
        headers = _decode_headers(scope)
        if not guard.body_allowed(headers):
            await _reply(send, 413, "MEDIA_TOO_LARGE", "Request body too large.")
            return
        ip = guard.client_ip(headers, _peer_ip(scope))
        retry = guard.suppressed_retry(ip)
        if retry > 0:
            await _reply(
                send, 429, "TOO_MANY_REQUESTS", "Too many requests.", retry
            )
            return
        if not await guard.acquire_slot():
            await _reply(
                send,
                503,
                "SERVER_OVERLOADED",
                "Server is overloaded. Try again shortly.",
                1,
            )
            return
        try:
            retry = await guard.check_ip(ip)
            if retry > 0:
                await _reply(
                    send, 429, "TOO_MANY_REQUESTS", "Too many requests.", retry
                )
                return
            await self._app(scope, receive, send)
        finally:
            guard.release_slot()

    def reset(self) -> None:
        """Drop cached guards (test isolation and manual unban hook)."""
        self._guards.clear()

    @classmethod
    def reset_all(cls, app: Any) -> None:
        """Walk an app's middleware stack and reset every guard (tests)."""
        stack = getattr(app, "middleware_stack", None)
        while stack is not None:
            if isinstance(stack, cls):
                stack.reset()
            stack = getattr(stack, "app", None)

    def _guard_for(self, scope: Scope) -> EdgeGuard:
        """One EdgeGuard per resolved settings signature (usually one)."""
        if self._fixed_guard is not None:
            return self._fixed_guard
        settings = _resolve_settings(scope)
        policy = GuardPolicy.from_settings(settings)
        key = (policy, settings.scylla_keyspace)
        guard = self._guards.get(key)
        if guard is None:
            if len(self._guards) >= _GUARD_CACHE_LIMIT:
                self._guards.pop(next(iter(self._guards)))
            from core.dependencies import build_edge_guard

            guard = build_edge_guard(settings)
            self._guards[key] = guard
        return guard


def _resolve_settings(scope: Scope) -> Settings:
    """Resolve Settings honoring dependency_overrides (test injection)."""
    app = scope.get("app")
    overrides = getattr(app, "dependency_overrides", None) or {}
    return overrides.get(get_settings, get_settings)()


def _decode_headers(scope: Scope) -> dict[str, str]:
    return {
        key.decode("latin-1"): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }


def _peer_ip(scope: Scope) -> str | None:
    client = scope.get("client")
    return client[0] if client else None


async def _reply(
    send: Send,
    status: int,
    code: str,
    message: str,
    retry_after: float | None = None,
) -> None:
    """Write the standard {code, message} envelope at ASGI level."""
    body = json.dumps({"code": code, "message": message}).encode()
    headers = [(b"content-type", b"application/json")]
    if retry_after is not None:
        headers.append(
            (b"retry-after", str(max(1, math.ceil(retry_after))).encode())
        )
    await send(
        {"type": "http.response.start", "status": status, "headers": headers}
    )
    await send({"type": "http.response.body", "body": body})
