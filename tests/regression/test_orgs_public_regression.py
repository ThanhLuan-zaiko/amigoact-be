"""Regression tests: frozen public org directory contracts."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"


async def test_public_page_envelope_contract_locked(client: AsyncClient) -> None:
    """GET /orgs is guest-readable and freezes the public card shape."""
    await client.post(
        "/auth/register",
        json={
            "email": "pubpager@example.com", "phone": "0344123999",
            "password": PASSWORD, "full_name": "Pub Pager",
        },
    )
    logged = await client.post(
        "/auth/login",
        json={"email": "pubpager@example.com", "password": PASSWORD},
    )
    headers = {"Authorization": f"Bearer {logged.json()['access_token']}"}
    made = await client.post(
        "/orgs",
        json={
            "name": "Reg Club", "slug": "reg-club", "description": "",
            "kind": "club", "email": "secret@club.vn",
        },
        headers=headers,
    )
    assert made.status_code == 201

    # No Authorization header at all: guests read the directory.
    page = await client.get("/orgs?kind=club")
    assert page.status_code == 200
    body = page.json()
    assert set(body.keys()) == {"items", "total", "counts"}
    card = next(o for o in body["items"] if o["slug"] == "reg-club")
    assert set(card.keys()) == {
        "id", "name", "slug", "description", "kind", "member_count",
        "join_policy", "city", "country", "verified_at", "logo_url",
        "cover_url", "created_at",
    }
    assert "reg-club" in [o["slug"] for o in body["items"]]


async def test_public_detail_contract_locked(client: AsyncClient) -> None:
    """GET /orgs/{slug} freezes the guest profile shape; PII stays out."""
    await client.post(
        "/auth/register",
        json={
            "email": "detpager@example.com", "phone": "0344123888",
            "password": PASSWORD, "full_name": "Det Pager",
        },
    )
    logged = await client.post(
        "/auth/login",
        json={"email": "detpager@example.com", "password": PASSWORD},
    )
    headers = {"Authorization": f"Bearer {logged.json()['access_token']}"}
    made = await client.post(
        "/orgs",
        json={
            "name": "Det Biz", "slug": "det-biz", "description": "",
            "kind": "business", "tax_code": "0309876543",
            "legal_rep_name": "Nguyen Van A", "legal_rep_id": "012345678901",
            "email": "hi@biz.vn",
        },
        headers=headers,
    )
    assert made.status_code == 201, made.text

    detail = await client.get("/orgs/det-biz")
    assert detail.status_code == 200
    body = detail.json()
    assert set(body.keys()) == {
        "id", "name", "slug", "description", "kind", "member_count",
        "join_policy", "email", "phone", "website", "address", "city",
        "country", "legal_status", "legal_name", "license_number",
        "tax_code", "verified_at", "logo_url", "cover_url", "gallery",
        "activity_count", "activities", "created_at",
    }
    assert body["tax_code"] == "0309876543"
    assert body["legal_status"] == "pending"

    # Route order: /orgs/mine still resolves to the auth-only listing.
    mine = await client.get("/orgs/mine")
    assert mine.status_code == 401
