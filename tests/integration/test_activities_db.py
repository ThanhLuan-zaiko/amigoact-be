"""Integration tests: activity lifecycle over HTTP (amigoact_test)."""

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


async def _org(client: AsyncClient, headers: dict, slug: str) -> str:
    created = await client.post(
        "/orgs",
        json={
            "name": f"Club {slug}",
            "slug": slug,
            "description": "",
            "kind": "club",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


_BODY = {
    "title": "Beach Cleanup Day",
    "description": "Clean the beach together",
    "location": "Vung Tau",
    "city": "Vung Tau",
    "is_remote": False,
    "start_at": "2030-06-01T08:00:00Z",
    "end_at": "2030-06-01T12:00:00Z",
    "hours_awarded": 4.0,
}


async def test_full_lifecycle_and_discovery(client: AsyncClient) -> None:
    owner = _headers(await _token(client, "a.own@example.com", "0903000010"))
    anon_member = _headers(
        await _token(client, "a.guest@example.com", "0903000011")
    )
    org_id = await _org(client, owner, "act-club")

    created = await client.post(
        f"/orgs/{org_id}/activities",
        json=_BODY,
        headers=owner,
    )
    assert created.status_code == 201, created.text
    activity = created.json()
    assert activity["status"] == "draft"
    assert activity["slug"] == "beach-cleanup-day"
    aid = activity["id"]

    hidden = await client.get(f"/activities/{aid}")
    assert hidden.status_code == 404

    dup_slug = await client.post(
        f"/orgs/{org_id}/activities",
        json={**_BODY, "title": "Same Slug Day", "slug": "beach-cleanup-day"},
        headers=owner,
    )
    assert dup_slug.status_code == 409
    assert dup_slug.json()["code"] == "SLUG_TAKEN"

    forbidden = await client.post(
        f"/orgs/{org_id}/activities/{aid}/status",
        json={"status": "published"},
        headers=anon_member,
    )
    assert forbidden.status_code == 403

    published = await client.post(
        f"/orgs/{org_id}/activities/{aid}/status",
        json={"status": "published"},
        headers=owner,
    )
    assert published.status_code == 200, published.text
    assert published.json()["published_at"] is not None

    feed = await client.get("/activities?status=published")
    assert feed.status_code == 200
    ids = [row["id"] for row in feed.json()]
    assert aid in ids

    by_slug = await client.get(
        f"/orgs/{org_id}/activities/by-slug/beach-cleanup-day"
    )
    assert by_slug.status_code == 200
    assert by_slug.json()["id"] == aid

    completed = await client.post(
        f"/orgs/{org_id}/activities/{aid}/status",
        json={"status": "completed"},
        headers=owner,
    )
    assert completed.status_code == 200

    backwards = await client.post(
        f"/orgs/{org_id}/activities/{aid}/status",
        json={"status": "draft"},
        headers=owner,
    )
    assert backwards.status_code == 400


async def test_detail_edges_flow(client: AsyncClient) -> None:
    owner_tok = await _token(client, "b.own@example.com", "0903000012")
    member_tok = await _token(client, "b.mem@example.com", "0903000013")
    owner = _headers(owner_tok)
    org_id = await _org(client, owner, "detail-club")

    me = await client.get("/auth/me", headers=_headers(member_tok))
    member_id = me.json()["id"]
    invited = await client.post(
        f"/orgs/{org_id}/members",
        json={"email": "b.mem@example.com"},
        headers=owner,
    )
    assert invited.status_code == 201, invited.text
    accepted = await client.post(
        f"/orgs/{org_id}/members/me/accept",
        headers=_headers(member_tok),
    )
    assert accepted.status_code == 200, accepted.text

    created = await client.post(
        f"/orgs/{org_id}/activities", json=_BODY, headers=owner
    )
    aid = created.json()["id"]

    skill = (await client.get("/skills")).json()[0]
    detailed = await client.put(
        f"/orgs/{org_id}/activities/{aid}/skills",
        json={"skills": [{"skill_id": skill["id"], "is_required": True}]},
        headers=owner,
    )
    assert detailed.status_code == 200, detailed.text
    assert detailed.json()["skills"][0]["is_required"] is True

    staffed = await client.put(
        f"/orgs/{org_id}/activities/{aid}/staff",
        json={"staff": [{"user_id": member_id, "staff_role": "supervisor"}]},
        headers=owner,
    )
    assert staffed.status_code == 200, staffed.text
    assert staffed.json()["staff"][0]["user_id"] == member_id

    scheduled = await client.post(
        f"/orgs/{org_id}/activities/{aid}/schedules",
        json={
            "title": "Morning shift",
            "location": "Gate A",
            "start_at": "2030-06-01T08:00:00Z",
            "end_at": "2030-06-01T10:00:00Z",
        },
        headers=owner,
    )
    assert scheduled.status_code == 201, scheduled.text
    assert scheduled.json()["schedules"][0]["title"] == "Morning shift"

    announced = await client.post(
        f"/orgs/{org_id}/activities/{aid}/announcements",
        json={"title": "Bring water", "body": "It will be hot."},
        headers=owner,
    )
    assert announced.status_code == 201

    member_view = await client.get(
        f"/orgs/{org_id}/activities/{aid}/detail",
        headers=_headers(member_tok),
    )
    assert member_view.status_code == 200
    assert member_view.json()["announcements"][0]["title"] == "Bring water"

    anonymous = await client.get(f"/orgs/{org_id}/activities/{aid}/detail")
    assert anonymous.status_code == 404


async def test_categories_seeded_and_org_scoped(
    client: AsyncClient,
) -> None:
    owner = _headers(await _token(client, "c.own@example.com", "0903000014"))
    org_id = await _org(client, owner, "cat-club")

    catalog = await client.get("/categories")
    assert catalog.status_code == 200
    rows = catalog.json()
    assert len(rows) >= 8
    assert any(r["slug"] == "environment" for r in rows)
    assert all(not r["org_scoped"] for r in rows)

    created = await client.post(
        f"/orgs/{org_id}/categories",
        json={
            "name": "Club Fest",
            "slug": "club-fest",
            "default_hours": 2.0,
        },
        headers=owner,
    )
    assert created.status_code == 201, created.text
    assert created.json()["org_scoped"] is True

    scoped = await client.get(f"/categories?org_id={org_id}", headers=owner)
    slugs = {r["slug"] for r in scoped.json()}
    assert "club-fest" in slugs

    env = next(r for r in rows if r["slug"] == "environment")
    created = await client.post(
        f"/orgs/{org_id}/activities",
        json={**_BODY, "category_id": env["id"]},
        headers=owner,
    )
    aid = created.json()["id"]
    await client.post(
        f"/orgs/{org_id}/activities/{aid}/status",
        json={"status": "published"},
        headers=owner,
    )
    filtered = await client.get(f"/activities?category_id={env['id']}")
    assert any(r["id"] == aid for r in filtered.json())
