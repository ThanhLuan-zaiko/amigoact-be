"""Integration tests: activity trash lifecycle over HTTP (amigoact_test)."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"

_BODY = {
    "title": "Cleanup Day",
    "description": "River cleanup",
    "location": "Hue",
    "city": "Hue",
    "is_remote": False,
    "start_at": "2030-08-01T08:00:00Z",
    "hours_awarded": 4.0,
}


async def _headers(client: AsyncClient, email: str, phone: str) -> dict:
    await client.post(
        "/auth/register",
        json={
            "email": email,
            "phone": phone,
            "password": PASSWORD,
            "full_name": "Del User",
        },
    )
    logged = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {logged.json()['access_token']}"}


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


async def _activity(
    client: AsyncClient, org_id: str, headers: dict, title: str
) -> str:
    res = await client.post(
        f"/orgs/{org_id}/activities",
        json={**_BODY, "title": title},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def test_trash_lifecycle_over_http(client: AsyncClient) -> None:
    owner = await _headers(client, "d.own@example.com", "0903000040")
    org_id = await _org(client, owner, "del-club")
    aid = await _activity(client, org_id, owner, "Doomed Run")
    pub = await client.post(
        f"/orgs/{org_id}/activities/{aid}/status",
        json={"status": "published"},
        headers=owner,
    )
    assert pub.status_code == 200, pub.text

    deleted = await client.delete(
        f"/orgs/{org_id}/activities/{aid}", headers=owner
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_at"] is not None

    live = await client.get(f"/orgs/{org_id}/activities", headers=owner)
    assert all(r["id"] != aid for r in live.json())

    trash = await client.get(
        f"/orgs/{org_id}/activities?trash=1", headers=owner
    )
    assert [r["id"] for r in trash.json()] == [aid]
    assert trash.json()[0]["deleted_at"] is not None

    public = await client.get("/activities?status=published")
    assert all(r["id"] != aid for r in public.json())

    gone = await client.get(f"/activities/{aid}")
    assert gone.status_code == 404

    blocked = await client.patch(
        f"/orgs/{org_id}/activities/{aid}",
        json=_BODY,
        headers=owner,
    )
    assert blocked.status_code == 410
    assert blocked.json()["code"] == "ACTIVITY_DELETED"

    restored = await client.post(
        f"/orgs/{org_id}/activities/{aid}/restore", headers=owner
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["deleted_at"] is None

    back = await client.get(f"/activities/{aid}")
    assert back.status_code == 200
    assert back.json()["status"] == "published"


async def test_hard_delete_and_authz(client: AsyncClient) -> None:
    owner = await _headers(client, "d2.own@example.com", "0903000041")
    stranger = await _headers(client, "d2.str@example.com", "0903000042")
    org_id = await _org(client, owner, "del-club2")
    aid = await _activity(client, org_id, owner, "Purge Me")

    denied = await client.delete(
        f"/orgs/{org_id}/activities/{aid}?hard=true", headers=stranger
    )
    assert denied.status_code == 403

    purged = await client.delete(
        f"/orgs/{org_id}/activities/{aid}?hard=true", headers=owner
    )
    assert purged.status_code == 204

    assert (await client.get(f"/activities/{aid}")).status_code == 404
    trash = await client.get(
        f"/orgs/{org_id}/activities?trash=1", headers=owner
    )
    assert trash.json() == []

    restored = await client.post(
        f"/orgs/{org_id}/activities/{aid}/restore", headers=owner
    )
    assert restored.status_code == 404
