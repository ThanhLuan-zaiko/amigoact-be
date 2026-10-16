"""Pure-ASGI middleware honoring the Idempotency-Key request header.

Mutating requests carrying `Idempotency-Key` claim a row in
`idempotency_keys` before reaching the route. A completed claim replays
the stored response verbatim; an in-progress one rejects with 409 so a
double-click never runs the handler twice. The key is scoped by
method+path+user so one client key cannot replay across endpoints.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from core.config import get_settings
from core.durability import CqlIdempotencyStore, IdempotencyStore
from core.security import utcnow

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    Message = dict
    Receive = Callable[[], Awaitable[Message]]
    Send = Callable[[Message], Awaitable[None]]

logger = logging.getLogger("amigoact.idempotency")

_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_MAX_KEY_LEN = 128
_STORE_CACHE_LIMIT = 4


class IdempotencyMiddleware:
    """Claim-check-replay around mutating requests with Idempotency-Key."""

    def __init__(self, app, store: IdempotencyStore | None = None) -> None:
        self._app = app
        self._fixed_store = store
        self._stores: dict[str, IdempotencyStore] = {}

    async def __call__(self, scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in _MUTATING:
            await self._app(scope, receive, send)
            return
        raw_key = _header(scope, b"idempotency-key")
        if raw_key is None or not raw_key or len(raw_key) > _MAX_KEY_LEN:
            await self._app(scope, receive, send)
            return
        store = self._store_for(scope)
        scoped = _scoped_key(scope, raw_key)
        user_id = _bearer_user(scope)
        try:
            prior = await asyncio.to_thread(
                store.claim, scoped, user_id, utcnow()
            )
        except Exception as exc:
            logger.warning("idempotency store unavailable: %s", exc)
            await self._app(scope, receive, send)
            return
        if prior == "in_progress":
            await _reply(
                send,
                409,
                "IDEMPOTENCY_IN_PROGRESS",
                "A request with this key is still running.",
            )
            return
        if prior is not None:
            await _replay(send, prior)
            return
        await self._run_and_store(scope, receive, send, store, scoped)

    async def _run_and_store(
        self, scope, receive: Receive, send: Send, store, key: str
    ) -> None:
        status: list[int] = []
        body = bytearray()

        async def capture(message: Message) -> None:
            if message["type"] == "http.response.start":
                status.append(message["status"])
            elif message["type"] == "http.response.body":
                body.extend(message.get("body", b""))
            await send(message)

        try:
            await self._app(scope, receive, capture)
        except Exception:
            await asyncio.to_thread(store.fail, key, utcnow())
            raise
        code = status[0] if status else 500
        payload = _envelope(code, bytes(body))
        await asyncio.to_thread(
            store.complete if code < 500 else store.fail,
            key,
            *((payload, utcnow()) if code < 500 else (utcnow(),)),
        )

    def _store_for(self, scope) -> IdempotencyStore:
        if self._fixed_store is not None:
            return self._fixed_store
        settings = _resolve_settings(scope)
        keyspace = settings.scylla_keyspace
        store = self._stores.get(keyspace)
        if store is None:
            if len(self._stores) >= _STORE_CACHE_LIMIT:
                self._stores.pop(next(iter(self._stores)))
            store = CqlIdempotencyStore(keyspace)
            self._stores[keyspace] = store
        return store


def _header(scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1").strip()
    return None


def _bearer_user(scope) -> UUID | None:
    """Scope the key to the caller when a bearer token is present."""
    token = _header(scope, b"authorization")
    if token is None or not token.lower().startswith("bearer "):
        return None
    try:
        from core.security import decode_access_token

        claims = decode_access_token(
            token[7:].strip(), _resolve_settings(scope).jwt_secret
        )
        sub = claims.get("sub")
        return UUID(str(sub)) if sub else None
    except Exception:
        return None


def _scoped_key(scope, raw_key: str) -> str:
    basis = f"{scope.get('method')}:{scope.get('path')}:{raw_key}"
    return hashlib.sha256(basis.encode()).hexdigest()


def _envelope(status: int, body: bytes) -> str:
    import json

    return json.dumps({"status": status, "body": body.decode("utf-8", "replace")})


async def _replay(send: Send, payload: str) -> None:
    import json

    try:
        stored = json.loads(payload)
        status = int(stored["status"])
        body = stored["body"].encode()
    except (ValueError, KeyError, TypeError):
        status, body = 200, b"{}"
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"idempotency-replayed", b"true"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _reply(send: Send, status: int, code: str, message: str) -> None:
    import json

    body = json.dumps({"code": code, "message": message}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _resolve_settings(scope):
    app = scope.get("app")
    overrides = getattr(app, "dependency_overrides", None) or {}
    return overrides.get(get_settings, get_settings)()
