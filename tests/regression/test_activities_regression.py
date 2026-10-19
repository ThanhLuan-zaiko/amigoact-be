"""Regression: freeze Phase 3 activity response shapes and rules."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"


async def _headers(client: AsyncClient, email: str, phone: str) -> dict:
    await client.post(
        "/auth/register",
        json={
            "email": email,
            "phone": phone,
            "password": PASSWORD,
            "full_name": "Reg User",
        },
    )
    logged = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {logged.json()['access_token']}"}


ACTIVITY_KEYS = {
    "id", "org_id", "category_id", "title", "slug", "description",
    "location", "address", "city", "latitude", "longitude", "is_remote",
    "status", "max_participants", "start_at", "end_at", "hours_awarded",
    "registration_deadline", "person_in_charge_id", "published_at",
    "created_at", "updated_at", "deleted_at", "tags",
}


async def test_activity_response_shape_and_slug_lifecycle(
    client: AsyncClient,
) -> None:
    """Contract: activity DTO keys + slug stays claimed after updates."""
    headers = await _headers(client, "r.act@example.com", "0903000020")
    org = await client.post(
        "/orgs",
        json={
            "name": "Reg Club", "slug": "reg-club",
            "description": "", "kind": "club",
        },
        headers=headers,
    )
    org_id = org.json()["id"]
    created = await client.post(
        f"/orgs/{org_id}/activities",
        json={
            "title": "Reg Run", "slug": "reg-run",
            "location": "Park", "is_remote": False,
            "hours_awarded": 1.0,
            "start_at": "2030-06-02T08:00:00Z",
        },
        headers=headers,
    )
    body = created.json()
    assert set(body.keys()) == ACTIVITY_KEYS

    aid = body["id"]
    updated = await client.patch(
        f"/orgs/{org_id}/activities/{aid}",
        json={
            "title": "Reg Run 2025",
            "start_at": "2030-06-02T08:00:00Z",
            "is_remote": False,
            "hours_awarded": 1.0,
        },
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["slug"] == "reg-run"

    dup = await client.post(
        f"/orgs/{org_id}/activities",
        json={
            "title": "Steal", "slug": "reg-run",
            "location": "X", "is_remote": True,
            "hours_awarded": 1.0,
            "start_at": "2030-06-02T08:00:00Z",
        },
        headers=headers,
    )
    assert dup.status_code == 409
    assert dup.json()["code"] == "SLUG_TAKEN"

    bad_slug = await client.post(
        f"/orgs/{org_id}/activities",
        json={
            "title": "Bad", "slug": "UPPER!! slug--x",
            "location": "X", "is_remote": True,
            "hours_awarded": 1.0,
            "start_at": "2030-06-02T08:00:00Z",
        },
        headers=headers,
    )
    assert bad_slug.status_code == 422

    unauth = await client.post(
        f"/orgs/{org_id}/activities",
        json={"title": "Nope", "location": "X", "is_remote": True,
              "hours_awarded": 1.0,
              "start_at": "2030-06-02T08:00:00Z"},
    )
    assert unauth.status_code == 401


async def test_tag_contract(client: AsyncClient) -> None:
    """Contract: tag DTO keys, feed exposes tags, unknown tag -> []."""
    headers = await _headers(client, "r.tag@example.com", "0903000021")
    org = await client.post(
        "/orgs",
        json={
            "name": "Tag Club", "slug": "reg-tag-club",
            "description": "", "kind": "club",
        },
        headers=headers,
    )
    org_id = org.json()["id"]
    created = await client.post(
        f"/orgs/{org_id}/activities",
        json={
            "title": "Tagged Run", "location": "Park",
            "is_remote": False, "hours_awarded": 1.0,
            "start_at": "2030-06-03T08:00:00Z",
            "tags": ["C\u1ed9ng \u0111\u1ed3ng"],
        },
        headers=headers,
    )
    assert created.status_code == 201
    tags = created.json()["tags"]
    assert len(tags) == 1
    assert set(tags[0].keys()) == {"name", "slug"}
    assert tags[0]["slug"] == "cong-dong"

    aid = created.json()["id"]
    await client.post(
        f"/orgs/{org_id}/activities/{aid}/status",
        json={"status": "published"},
        headers=headers,
    )
    feed = await client.get("/activities?tag=cong-dong")
    assert feed.status_code == 200
    row = next(r for r in feed.json() if r["id"] == aid)
    assert row["tags"] == [{"name": "C\u1ed9ng \u0111\u1ed3ng", "slug": "cong-dong"}]

    miss = await client.get("/activities?tag=no-such-tag")
    assert miss.status_code == 200
    assert all(r["id"] != aid for r in miss.json())

    catalog = await client.get("/tags?q=cong")
    assert all(set(t.keys()) == {"name", "slug"}
               for t in catalog.json())

    overflow = await client.post(
        f"/orgs/{org_id}/activities",
        json={
            "title": "Tag Flood", "location": "X", "is_remote": True,
            "hours_awarded": 1.0,
            "start_at": "2030-06-03T08:00:00Z",
            "tags": [f"tag{i}" for i in range(11)],
        },
        headers=headers,
    )
    assert overflow.status_code == 422
