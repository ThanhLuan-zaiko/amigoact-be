"""Pure-ASGI middleware: API error responses are never HTTP-cacheable."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    Scope = dict[str, object]
    Message = dict[str, object]
    Receive = Callable[[], Awaitable[Message]]
    Send = Callable[[Message], Awaitable[None]]

_CACHE_CONTROL = b"cache-control"
_NO_STORE = b"no-store"


class NoStoreErrorsMiddleware:
    """Stamp ``Cache-Control: no-store`` on every ``>=400`` response.

    Browsers may heuristically cache 404/410 (cacheable-by-default statuses),
    which pins a stale error long after the resource recovered - e.g. an
    ORG_DELETED response served from disk cache for a restored org.
    """

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def send_no_store(message: Message) -> None:
            if (
                message["type"] == "http.response.start"
                and message["status"] >= 400  # type: ignore[operator]
            ):
                headers = message.setdefault("headers", [])
                if not any(k.lower() == _CACHE_CONTROL for k, _ in headers):  # type: ignore[union-attr]
                    headers.append((_CACHE_CONTROL, _NO_STORE))  # type: ignore[union-attr]
            await send(message)

        await self._app(scope, receive, send_no_store)
