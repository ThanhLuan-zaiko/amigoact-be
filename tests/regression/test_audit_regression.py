"""Regression locks: Phase 7 audit feed shape + refresh rate limit."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_audit_db import (
    _headers,
    _org,
    _token,
)


async def test_audit_feed_contract(client: AsyncClient) -> None:
    """Freeze the audit entry payload shape for the FE."""
    owner = _headers(await _token(client, "ar7a@test.dev", "0913000001"))
    org_id = await _org(client, owner, "audit-reg")
    await client.post(
        f"/orgs/{org_id}/members",
        json={"email": "ghost@test.dev"},
        headers=_headers(
            await _token(client, "ar7b@test.dev", "0913000002")
        ),
    )
    feed = await client.get(f"/orgs/{org_id}/audit", headers=owner)
    assert feed.status_code == 200
    assert set(feed.json()) == {"items"}
    assert set(feed.json()["items"][0]) == {
        "log_id",
        "occurred_at",
        "actor_id",
        "actor_name",
        "action",
        "resource_type",
        "resource_id",
        "result",
    }


async def test_refresh_rate_limit_error_code(client: AsyncClient) -> None:
    """TooManyRequestsError stays a 429 with RATE_LIMITED shape."""
    headers = _headers(await _token(client, "ar7c@test.dev", "0913000003"))
    last = None
    for _ in range(40):
        last = await client.post("/auth/refresh", headers=headers)
        if last.status_code == 429:
            break
    assert last is not None and last.status_code == 429
    body = last.json()
    assert body["code"] == "TOO_MANY_REQUESTS"
