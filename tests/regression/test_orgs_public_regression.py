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
        "activity_count", "activities",
        "announcement_count", "announcements", "created_at",
    }
    assert body["tax_code"] == "0309876543"
    assert body["legal_status"] == "pending"

    # Route order: /orgs/mine still resolves to the auth-only listing.
    mine = await client.get("/orgs/mine")
    assert mine.status_code == 401


async def test_public_announcement_contract_locked(client: AsyncClient) -> None:
    """Guest announcement read reuses the internal PostResponse shape and
    its teaser items freeze their own field set on the profile."""
    await client.post(
        "/auth/register",
        json={
            "email": "annpager@example.com", "phone": "0344123777",
            "password": PASSWORD, "full_name": "Ann Pager",
        },
    )
    logged = await client.post(
        "/auth/login",
        json={"email": "annpager@example.com", "password": PASSWORD},
    )
    headers = {"Authorization": f"Bearer {logged.json()['access_token']}"}
    made = await client.post(
        "/orgs",
        json={
            "name": "Ann Club", "slug": "ann-club", "description": "",
            "kind": "club",
        },
        headers=headers,
    )
    assert made.status_code == 201
    org_id = made.json()["id"]
    posted = await client.post(
        f"/orgs/{org_id}/posts",
        json={"kind": "announcement", "title": "News", "body": "Body"},
        headers=headers,
    )
    assert posted.status_code == 201, posted.text
    post_id = posted.json()["post_id"]

    detail = await client.get("/orgs/ann-club")  # guest: no auth
    assert detail.status_code == 200
    item = detail.json()["announcements"][0]
    assert set(item.keys()) == {
        "id", "title", "excerpt", "cover_url", "author_name",
        "published_at", "comment_count",
    }

    article = await client.get(f"/orgs/ann-club/announcements/{post_id}")
    assert article.status_code == 200
    assert set(article.json().keys()) == {
        "post_id", "org_id", "author_id", "author_name", "kind", "title",
        "body", "pinned_at", "edited_at", "media", "comment_count",
        "status", "blocks", "cover_media_id", "published_at",
        "deleted_at", "updated_at", "created_at", "revision_of",
    }
    assert article.json()["kind"] == "announcement"
    assert article.json()["status"] == "published"

    listing = await client.get("/orgs/ann-club/announcements")
    assert listing.status_code == 200
    assert set(listing.json().keys()) == {"items", "total"}
    assert listing.json()["total"] == 1
    assert set(listing.json()["items"][0].keys()) == {
        "id", "title", "excerpt", "cover_url", "author_name",
        "published_at", "comment_count",
    }
