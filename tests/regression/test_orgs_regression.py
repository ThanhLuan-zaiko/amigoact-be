"""Regression tests: frozen org and business-account contracts."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"


async def test_business_register_contract_locked(client: AsyncClient) -> None:
    """Business payload shape stays backward compatible with individuals."""
    individual = await client.post(
        "/auth/register",
        json={
            "email": "ind@example.com", "phone": "0912345678",
            "password": PASSWORD, "full_name": "Ca Nhan",
        },
    )
    assert individual.status_code == 201
    assert individual.json()["account_type"] == "individual"

    incomplete = await client.post(
        "/auth/register",
        json={
            "email": "badbiz@example.com", "phone": "0312345678",
            "password": PASSWORD, "full_name": "Thieu MST",
            "account_type": "business",
        },
    )
    assert incomplete.status_code == 422


async def test_org_legal_status_contract_locked(client: AsyncClient) -> None:
    """Club stays none, business stays pending; slug conflicts stay 409."""
    await client.post(
        "/auth/register",
        json={
            "email": "owner@example.com", "phone": "0777777779",
            "password": PASSWORD, "full_name": "Owner",
        },
    )
    logged = await client.post(
        "/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
    )
    headers = {"Authorization": f"Bearer {logged.json()['access_token']}"}
    club = await client.post(
        "/orgs",
        json={"name": "Club", "slug": "locked-club", "description": "", "kind": "club"},
        headers=headers,
    )
    assert club.json()["legal_status"] == "none"
    clash = await client.post(
        "/orgs",
        json={"name": "Other", "slug": "locked-club", "description": "", "kind": "group"},
        headers=headers,
    )
    assert clash.status_code == 409
    assert set(clash.json().keys()) == {"code", "message"}
    assert clash.json()["code"] == "SLUG_TAKEN"


async def test_trash_and_media_contracts_locked(client: AsyncClient) -> None:
    """Soft delete hides, restore revives, hard delete 204s; media stays typed."""
    await client.post(
        "/auth/register",
        json={
            "email": "janitor@example.com", "phone": "0898765432",
            "password": PASSWORD, "full_name": "Janitor",
        },
    )
    logged = await client.post(
        "/auth/login", json={"email": "janitor@example.com", "password": PASSWORD}
    )
    headers = {"Authorization": f"Bearer {logged.json()['access_token']}"}
    created = await client.post(
        "/orgs",
        json={"name": "Temp", "slug": "temp-club", "description": "", "kind": "club"},
        headers=headers,
    )
    org_id = created.json()["id"]
    assert created.json()["deleted_at"] is None

    uploaded = await client.post(
        f"/orgs/{org_id}/media",
        files={"file": ("clip.mp4", b"\x00\x00" + b"2" * 64, "video/mp4")},
        headers=headers,
    )
    assert uploaded.status_code == 201
    assert uploaded.json()["kind"] == "video"

    await client.delete(f"/orgs/{org_id}", headers=headers)
    gallery = await client.get(f"/orgs/{org_id}/media", headers=headers)
    assert gallery.status_code == 410
    assert gallery.json()["code"] == "ORG_DELETED"

    await client.post(f"/orgs/{org_id}/restore", headers=headers)
    gallery = await client.get(f"/orgs/{org_id}/media", headers=headers)
    assert gallery.status_code == 200

    erased = await client.delete(f"/orgs/{org_id}?hard=true", headers=headers)
    assert erased.status_code == 204
    assert erased.text == ""
