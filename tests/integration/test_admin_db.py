"""Integration tests: platform-admin verification queue over HTTP."""

from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import TEST_ADMIN_EMAIL

PASSWORD = "Aa1!secure"


async def _token(client: AsyncClient, email: str, phone: str) -> str:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "phone": phone,
            "password": PASSWORD,
            "full_name": "Test User",
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


async def _business_org(
    client: AsyncClient,
    headers: dict[str, str],
    slug: str,
    tax_code: str,
) -> str:
    created = await client.post(
        "/orgs",
        json={
            "name": f"Biz {slug}",
            "slug": slug,
            "description": "",
            "kind": "business",
            "tax_code": tax_code,
            "legal_rep_name": "Nguyen Van A",
            "legal_rep_id": "001234567890",
            "legal_rep_position": "Director",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["legal_status"] == "pending"
    return created.json()["id"]


async def test_admin_verification_queue_flow(client: AsyncClient) -> None:
    admin = _headers(await _token(client, TEST_ADMIN_EMAIL, "0900000001"))
    owner = _headers(await _token(client, "biz.owner@example.com", "0900000002"))
    org_id = await _business_org(client, owner, "biz-one", "0100100001")

    me = await client.get("/admin/me", headers=admin)
    assert me.json() == {"is_admin": True}
    me_owner = await client.get("/admin/me", headers=owner)
    assert me_owner.json() == {"is_admin": False}

    denied = await client.get("/admin/orgs", headers=owner)
    assert denied.status_code == 403
    assert denied.json()["code"] == "FORBIDDEN"

    pending = await client.get("/admin/orgs", headers=admin)
    assert pending.status_code == 200
    items = pending.json()["items"]
    assert [item["id"] for item in items] == [org_id]
    assert items[0]["owner_email"] == "biz.owner@example.com"
    assert items[0]["legal_status"] == "pending"

    verified = await client.post(f"/admin/orgs/{org_id}/verify", headers=admin)
    assert verified.status_code == 200, verified.text
    assert verified.json()["legal_status"] == "verified"
    assert verified.json()["verified_at"] is not None

    still_pending = await client.get("/admin/orgs", headers=admin)
    assert still_pending.json()["items"] == []
    verified_q = await client.get("/admin/orgs?status=verified", headers=admin)
    assert [i["id"] for i in verified_q.json()["items"]] == [org_id]

    again = await client.post(f"/admin/orgs/{org_id}/verify", headers=admin)
    assert again.status_code == 400
    assert again.json()["code"] == "INVALID_ORG_STATE"


async def test_admin_reject_and_notification(client: AsyncClient) -> None:
    admin = _headers(await _token(client, TEST_ADMIN_EMAIL, "0900000003"))
    owner = _headers(await _token(client, "biz.owner2@example.com", "0900000004"))
    org_id = await _business_org(client, owner, "biz-two", "0100100002")

    rejected = await client.post(
        f"/admin/orgs/{org_id}/reject",
        json={"reason": "Missing license scan"},
        headers=admin,
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["legal_status"] == "rejected"

    inbox = await client.get("/notifications", headers=owner)
    assert inbox.status_code == 200
    items = inbox.json()["items"]
    assert len(items) == 1
    assert items[0]["type"] == "organization"
    assert "xác minh" in items[0]["title"]


async def test_admin_grant_revoke_platform_role(client: AsyncClient) -> None:
    admin = _headers(await _token(client, TEST_ADMIN_EMAIL, "0900000005"))
    user = _headers(await _token(client, "promote@example.com", "0900000006"))
    me = await client.get("/auth/me", headers=user)
    user_id = me.json()["id"]

    granted = await client.post(
        "/admin/admins",
        json={"email": "promote@example.com"},
        headers=admin,
    )
    assert granted.status_code == 204

    missing = await client.post(
        "/admin/admins",
        json={"email": "ghost@example.com"},
        headers=admin,
    )
    assert missing.status_code == 404

    assert (await client.get("/admin/me", headers=user)).json() == {
        "is_admin": True
    }
    roster = await client.get("/admin/admins", headers=admin)
    assert [row["email"] for row in roster.json()] == [
        "promote@example.com"
    ]

    revoked = await client.delete(f"/admin/admins/{user_id}", headers=admin)
    assert revoked.status_code == 204
    assert (await client.get("/admin/me", headers=user)).json() == {
        "is_admin": False
    }
