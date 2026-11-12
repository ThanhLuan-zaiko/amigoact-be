"""Shared key between the Next.js server and this API.

Only the Next.js server calls the API over HTTP, so every HTTP request must
carry the key from `.env`. A request without it is refused before routing,
authentication, or validation run, so outsiders learn nothing about the API,
not even which fields a body needs.

The chat WebSocket is the one exception: the browser opens it directly with a
one-time ticket, which the Next.js server fetched with the key.
"""

import hmac
import json
from functools import lru_cache

from pydantic import Field
from starlette.types import ASGIApp, Receive, Scope, Send

from src.config import DotenvSettings

HEADER = "x-internal-key"
INVALID_CODE = "internal_key_invalid"


class InternalKeySettings(DotenvSettings):
    """Random secret of at least 32 characters, the same in both `.env` files."""

    internal_api_key: str = Field(min_length=32)


@lru_cache
def get_internal_key_settings() -> InternalKeySettings:
    return InternalKeySettings()


def key_matches(expected: str, provided: str | None) -> bool:
    """Constant-time comparison, so timing does not reveal the key."""
    if not provided:
        return False
    return hmac.compare_digest(expected.encode(), provided.encode())


def header_value(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == HEADER.encode():
            return bytes(value).decode("latin-1")
    return None


class InternalKeyMiddleware:
    """Pure ASGI middleware, so it runs before FastAPI parses or validates anything."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # Lifespan events and the chat socket pass. The socket checks its ticket.
            await self.app(scope, receive, send)
            return
        expected = get_internal_key_settings().internal_api_key
        if key_matches(expected, header_value(scope)):
            await self.app(scope, receive, send)
            return
        body = json.dumps({"detail": INVALID_CODE}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
