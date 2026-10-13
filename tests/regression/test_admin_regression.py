"""Regression: freeze admin + notification response contracts."""

from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import TEST_ADMIN_EMAIL

PASSWORD = "Aa1!secure"

ADMIN_ORG_KEYS = {
    "id",
    "name",
    "slug",
    "kind",
    "status",
    "legal_status",
    "tax_code",
    "legal_rep_name",
    "owner_id",
    "owner_name",
    "owner_email",
    "verified_at",
    "created_at",
}

NOTIFICATION_KEYS = {
    "id",
    "type",
    "title",
    "body",
    "status",
    "read_at",
    "created_at",
    "data",
}


async def _token(client: AsyncClient, email: str, phone: str) -> str:
    await client.post(
        "/auth/register",
        json={
            "email": email,
            "phone": phone,
            "password": PASSWORD,
            "full_name": "Test User",
        },
    )
    logged = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    return logged.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_admin_org_item_shape_is_frozen(client: AsyncClient) -> None:
    """Contract lock: queue rows keep their published key set."""
    admin = _headers(await _token(client, TEST_ADMIN_EMAIL, "0900000020"))
    owner = _headers(
        await _token(client, "reg.owner@example.com", "0900000021")
    )
    created = await client.post(
        "/orgs",
        json={
            "name": "Reg Biz",
            "slug": "reg-biz",
            "description": "",
            "kind": "business",
            "tax_code": "0100100010",
            "legal_rep_name": "Rep",
            "legal_rep_id": "001234567890",
        },
        headers=owner,
    )
    assert created.status_code == 201, created.text

    pending = await client.get("/admin/orgs", headers=admin)
    assert pending.status_code == 200
    assert set(pending.json()) == {"items", "total"}
    assert set(pending.json()["items"][0]) == ADMIN_ORG_KEYS

    verified = await client.post(
        f"/admin/orgs/{created.json()['id']}/verify", headers=admin
    )
    assert set(verified.json()) == ADMIN_ORG_KEYS


async def test_notification_item_shape_is_frozen(client: AsyncClient) -> None:
    """Contract lock: inbox rows keep their published key set."""
    owner = _headers(await _token(client, "reg.own2@example.com", "0900000022"))
    invitee = _headers(
        await _token(client, "reg.inv2@example.com", "0900000023")
    )
    created = await client.post(
        "/orgs",
        json={
            "name": "Reg Club",
            "slug": "reg-club",
            "description": "",
            "kind": "club",
        },
        headers=owner,
    )
    await client.post(
        f"/orgs/{created.json()['id']}/members",
        json={"email": "reg.inv2@example.com"},
        headers=owner,
    )

    inbox = await client.get("/notifications", headers=invitee)
    assert set(inbox.json()) == {"items", "total", "unread"}
    assert set(inbox.json()["items"][0]) == NOTIFICATION_KEYS


async def test_admin_endpoints_reject_anonymous(client: AsyncClient) -> None:
    """Every admin surface requires authentication (401, not 403)."""
    for path in ("/admin/me", "/admin/orgs", "/admin/admins"):
        response = await client.get(path)
        assert response.status_code == 401, path
        assert response.json()["code"] == "UNAUTHORIZED"
