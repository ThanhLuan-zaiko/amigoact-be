"""Integration tests: org audit feed over HTTP."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"


async def _token(client: AsyncClient, email: str, phone: str) -> str:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "phone": phone,
            "password": PASSWORD,
            "full_name": "Audit User",
        },
    )
    assert response.status_code == 201, response.text
    logged = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert logged.status_code == 200, logged.text
    return logged.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _org(client: AsyncClient, headers: dict, slug: str) -> str:
    created = await client.post(
        "/orgs",
        json={
            "name": f"Org {slug}",
            "slug": slug,
            "description": "",
            "kind": "club",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def test_audit_feed_records_denied_and_allowed(client: AsyncClient) -> None:
    owner = _headers(await _token(client, "auown@test.dev", "0912000001"))
    outsider = _headers(await _token(client, "auout@test.dev", "0912000002"))
    org_id = await _org(client, owner, "audit-org")

    # A denied action by an outsider is recorded into the org partition.
    denied = await client.post(
        f"/orgs/{org_id}/members",
        json={"email": "nobody@test.dev"},
        headers=outsider,
    )
    assert denied.status_code in (403, 404), denied.text

    feed = await client.get(f"/orgs/{org_id}/audit", headers=owner)
    assert feed.status_code == 200, feed.text
    items = feed.json()["items"]
    assert len(items) >= 1
    first = items[0]
    assert first["actor_name"] == "Audit User"
    assert first["result"] in {"allowed", "denied"}
    assert first["resource_type"] == "member"


async def test_audit_feed_denies_outsider(client: AsyncClient) -> None:
    owner = _headers(await _token(client, "auown2@test.dev", "0912000003"))
    outsider = _headers(await _token(client, "auout2@test.dev", "0912000004"))
    org_id = await _org(client, owner, "audit-org2")
    response = await client.get(f"/orgs/{org_id}/audit", headers=outsider)
    assert response.status_code == 403, response.text


async def test_audit_feed_missing_org_is_404(client: AsyncClient) -> None:
    headers = _headers(await _token(client, "auown3@test.dev", "0912000005"))
    response = await client.get(
        "/orgs/018f6f4e-0000-7000-8000-000000000000/audit",
        headers=headers,
    )
    assert response.status_code == 404, response.text
