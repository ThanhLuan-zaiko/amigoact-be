"""Pure-ASGI middleware: per-request latency header and slow-request log."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    Scope = dict[str, object]
    Message = dict[str, object]
    Receive = Callable[[], Awaitable[Message]]
    Send = Callable[[Message], Awaitable[None]]

logger = logging.getLogger("amigoact.timing")

_SERVER_TIMING = b"server-timing"


class TimingMiddleware:
    """Add ``Server-Timing: app;dur=<ms>`` and warn on slow requests.

    Only method, route path and duration are logged - never query strings,
    headers or bodies, which may carry tokens or personal data.
    """

    def __init__(self, app, slow_ms: float = 500.0) -> None:  # type: ignore[no-untyped-def]
        self._app = app
        self._slow_ms = slow_ms

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 0

        async def send_timed(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])  # type: ignore[arg-type]
                elapsed = (time.perf_counter() - started) * 1000
                headers = message.setdefault("headers", [])
                headers.append(  # type: ignore[union-attr]
                    (_SERVER_TIMING, f"app;dur={elapsed:.1f}".encode())
                )
            await send(message)

        try:
            await self._app(scope, receive, send_timed)
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            if elapsed >= self._slow_ms:
                logger.warning(
                    "Slow request: %s %s -> %d in %.0f ms",
                    scope.get("method"),
                    scope.get("path"),
                    status,
                    elapsed,
                )
