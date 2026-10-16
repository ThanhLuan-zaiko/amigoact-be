"""Unit tests for IdempotencyMiddleware + JobLeaseStore (no ScyllaDB)."""

from __future__ import annotations

import asyncio
import json

from core.durability import IdempotencyStore, JobLeaseStore
from core.idempotency_middleware import IdempotencyMiddleware


class FakeIdem(IdempotencyStore):
    """In-memory IdempotencyStore honoring the port semantics."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, str | None]] = {}
        self.claims = 0
        self.fail_calls = 0

    def claim(self, key, user_id, now):
        self.claims += 1
        row = self.rows.get(key)
        if row is None:
            self.rows[key] = ("in_progress", None)
            return None
        return row[1] if row[0] == "completed" else row[0]

    def complete(self, key, response_json, now):
        self.rows[key] = ("completed", response_json)

    def fail(self, key, now):
        self.fail_calls += 1
        self.rows[key] = ("failed", None)


class FakeLeases(JobLeaseStore):
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow
        self.acquired: list = []
        self.released: list = []

    def acquire(self, job_id, owner, ttl_seconds):
        self.acquired.append((job_id, owner))
        return self.allow

    def release(self, job_id, owner, status):
        self.released.append((job_id, owner, status))


async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b'{"ok":true}'})


def _scope(method="POST", key="abc-123", path="/items"):
    headers = []
    if key is not None:
        headers.append((b"idempotency-key", key.encode()))
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers,
        "app": None,
    }


async def _dispatch(mw, scope):
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b""}

    await mw(scope, receive, send)
    return sent


def _status(sent) -> int:
    return sent[0]["status"]


def _body(sent) -> bytes:
    return b"".join(m.get("body", b"") for m in sent[1:])


def test_passes_through_without_key():
    mw = IdempotencyMiddleware(_ok_app, store=FakeIdem())
    sent = asyncio.run(_dispatch(mw, _scope(key=None)))
    assert _status(sent) == 200


def test_passes_through_get():
    store = FakeIdem()
    mw = IdempotencyMiddleware(_ok_app, store=store)
    sent = asyncio.run(_dispatch(mw, _scope(method="GET")))
    assert _status(sent) == 200 and store.claims == 0


def test_first_run_stores_then_replays():
    store = FakeIdem()
    mw = IdempotencyMiddleware(_ok_app, store=store)
    scope = _scope()
    first = asyncio.run(_dispatch(mw, scope))
    assert _status(first) == 200
    second = asyncio.run(_dispatch(mw, scope))
    assert _status(second) == 200
    assert _body(second) == b'{"ok":true}'
    replayed = dict(second[0]["headers"])
    assert replayed.get(b"idempotency-replayed") == b"true"


def test_in_progress_conflicts():
    store = FakeIdem()
    scope = _scope()
    from core.idempotency_middleware import _scoped_key

    store.rows[_scoped_key(scope, "abc-123")] = ("in_progress", None)
    mw = IdempotencyMiddleware(_ok_app, store=store)
    sent = asyncio.run(_dispatch(mw, scope))
    assert _status(sent) == 409
    assert b"IDEMPOTENCY_IN_PROGRESS" in _body(sent)


def test_store_failure_fails_open():
    class Broken(FakeIdem):
        def claim(self, key, user_id, now):
            raise RuntimeError("db down")

    mw = IdempotencyMiddleware(_ok_app, store=Broken())
    sent = asyncio.run(_dispatch(mw, _scope()))
    assert _status(sent) == 200


def test_handler_error_marks_failed():
    async def boom(scope, receive, send):
        raise RuntimeError("handler exploded")

    store = FakeIdem()
    mw = IdempotencyMiddleware(boom, store=store)
    try:
        asyncio.run(_dispatch(mw, _scope()))
    except RuntimeError:
        pass
    assert store.fail_calls == 1


def test_export_lease_denied():
    from tests.unit.test_reports import _setup  # noqa: PLC0415

    service, parts, org_id, owner = _setup()
    service._leases = FakeLeases(allow=False)
    import pytest
    from core.exceptions import InvalidBusinessProfileError

    with pytest.raises(InvalidBusinessProfileError):
        service.request_export(org_id, owner, "stats_csv")


def test_export_lease_released():
    from tests.unit.test_reports import _setup  # noqa: PLC0415

    service, parts, org_id, owner = _setup()
    leases = FakeLeases()
    service._leases = leases
    job = service.request_export(org_id, owner, "stats_csv")
    assert leases.acquired == [(job.job_id, f"api:{owner}")]
    assert leases.released == [(job.job_id, f"api:{owner}", "done")]
