"""Regression: freeze the GET /announcements public contract.

The global timeline is the guest-facing social surface of the home
page: guests must read it, every item must carry the public teaser
fields plus org attribution, and non-announcement content must never
leak (BOARD.md 3.1, docs/REALTIME.md).
"""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"


async def _owner_headers(
    client: AsyncClient, slug: str, phone: str
) -> tuple[str, dict[str, str]]:
    registered = await client.post(
        "/auth/register",
        json={
            "email": f"{slug}@x.com",
            "phone": phone,
            "password": PASSWORD,
            "full_name": "Reg User",
        },
    )
    assert registered.status_code == 201, registered.text
    logged = await client.post(
        "/auth/login",
        json={"email": f"{slug}@x.com", "password": PASSWORD},
    )
    assert logged.status_code == 200, logged.text
    headers = {"Authorization": f"Bearer {logged.json()['access_token']}"}
    created = await client.post(
        "/orgs",
        json={
            "name": f"Name {slug}",
            "slug": slug,
            "description": "D",
            "kind": "club",
            "join_policy": "invite",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"], headers


async def test_announcements_contract_shape(client: AsyncClient) -> None:
    org_id, headers = await _owner_headers(client, "reg-feed", "0912347201")
    made = await client.post(
        f"/orgs/{org_id}/posts",
        json={"kind": "announcement", "title": "Hello", "body": "world"},
        headers=headers,
    )
    assert made.status_code == 201, made.text

    listed = await client.get("/announcements")
    assert listed.status_code == 200, listed.text
    page = listed.json()
    assert set(page.keys()) == {"items", "next_cursor"}
    mine = next(
        item for item in page["items"] if item["id"] == made.json()["post_id"]
    )
    assert set(mine.keys()) == {
        "id", "title", "excerpt", "cover_url", "author_name",
        "author_avatar_url", "published_at", "comment_count", "org",
        "media", "media_count", "tags",
    }
    assert mine["media"] == [] and mine["media_count"] == 0
    assert mine["tags"] == []
    tagged = await client.post(
        f"/orgs/{org_id}/posts",
        json={
            "kind": "announcement",
            "title": "Tagged",
            "body": "world",
            "tags": ["Hoc bong"],
        },
        headers=headers,
    )
    assert tagged.status_code == 201, tagged.text
    again = await client.get("/announcements")
    chip = next(
        item
        for item in again.json()["items"]
        if item["id"] == tagged.json()["post_id"]
    )
    assert chip["tags"] == [{"name": "Hoc bong", "slug": "hoc-bong"}]
    assert set(mine["org"].keys()) == {"id", "name", "slug", "logo_url"}
    assert mine["org"]["slug"] == "reg-feed"


async def test_announcements_never_leaks_member_content(
    client: AsyncClient,
) -> None:
    org_id, headers = await _owner_headers(client, "reg-leak", "0912347202")
    for payload in (
        {"kind": "discussion", "body": "internal"},
        {
            "kind": "announcement", "title": "Internal", "body": "b",
            "visibility": "members",
        },
        {
            "kind": "announcement", "title": "Draft", "body": "b",
            "status": "draft",
        },
    ):
        made = await client.post(
            f"/orgs/{org_id}/posts", json=payload, headers=headers
        )
        assert made.status_code == 201, made.text
    listed = await client.get("/announcements")
    assert listed.status_code == 200
    org_items = [
        item for item in listed.json()["items"]
        if item["org"]["id"] == org_id
    ]
    assert org_items == []
