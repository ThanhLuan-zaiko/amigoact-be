"""Integration: edge guard middleware against the real app + ScyllaDB."""

from __future__ import annotations

import main
from httpx import AsyncClient

from core.config import get_settings
from tests.conftest import TEST_KEYSPACE, _test_settings


def _guard_settings(**overrides):
    return _test_settings().model_copy(
        update={"guard_ip_max_hits": 3, "guard_queue_ms": 0, **overrides}
    )


def _edge_hits() -> int:
    """Total hits recorded in auth_rate_limits under 'edge:' buckets."""
    from cassandra.cqlengine.connection import get_session

    rows = (
        get_session()
        .execute(f"SELECT bucket, hits FROM {TEST_KEYSPACE}.auth_rate_limits")
        .all()
    )
    return sum(
        int(row["hits"])
        for row in rows
        if str(row["bucket"]).startswith("edge:")
    )


async def test_edge_guard_per_ip_limit(client: AsyncClient) -> None:
    """Past the limit an IP gets 429, then suppression short-circuits."""
    main.app.dependency_overrides[get_settings] = _guard_settings
    for _ in range(3):
        assert (await client.get("/")).status_code == 200
    blocked = await client.get("/")
    assert blocked.status_code == 429
    assert blocked.json() == {
        "code": "TOO_MANY_REQUESTS",
        "message": "Too many requests.",
    }
    assert int(blocked.headers["retry-after"]) >= 1
    suppressed = await client.get("/")
    assert suppressed.status_code == 429
    # The suppressed request was rejected without touching the counter.
    assert _edge_hits() == 4


async def test_edge_guard_exempt_paths_never_limited(
    client: AsyncClient,
) -> None:
    """Probe/doc endpoints bypass the guard and never write buckets."""
    main.app.dependency_overrides[get_settings] = _guard_settings
    for _ in range(6):
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/docs")).status_code == 200
        assert (await client.get("/openapi.json")).status_code == 200
    assert _edge_hits() == 0


async def test_edge_guard_disabled_passes_all(client: AsyncClient) -> None:
    """guard_enabled=false removes the wall entirely."""
    main.app.dependency_overrides[get_settings] = lambda: _guard_settings(
        guard_enabled=False, guard_ip_max_hits=1
    )
    for _ in range(8):
        assert (await client.get("/")).status_code == 200


async def test_edge_guard_counts_requests_per_ip(
    client: AsyncClient,
) -> None:
    """Normal traffic is counted once per request in ScyllaDB."""
    main.app.dependency_overrides[get_settings] = _guard_settings
    for _ in range(3):
        assert (await client.get("/")).status_code == 200
    assert _edge_hits() == 3
