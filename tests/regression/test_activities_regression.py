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
    "created_at", "updated_at",
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
