"""Integration tests: the public announcements timeline over HTTP."""

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
            "full_name": "Feed User",
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


async def _org_with_announcements(
    client: AsyncClient, slug: str, titles: list[str], phone: str
) -> tuple[str, dict[str, str], list[str]]:
    """One invite-policy org plus published announcements by the owner."""
    owner = await _token(client, f"{slug}-own@x.com", phone)
    owner_h = _headers(owner)
    created = await client.post(
        "/orgs",
        json={
            "name": f"Name {slug}",
            "slug": slug,
            "description": "D",
            "kind": "club",
            "join_policy": "invite",
        },
        headers=owner_h,
    )
    assert created.status_code == 201, created.text
    org_id = created.json()["id"]
    post_ids: list[str] = []
    for title in titles:
        made = await client.post(
            f"/orgs/{org_id}/posts",
            json={"kind": "announcement", "title": title, "body": "b"},
            headers=owner_h,
        )
        assert made.status_code == 201, made.text
        post_ids.append(made.json()["post_id"])
    return org_id, owner_h, post_ids


async def test_timeline_is_guest_readable_with_org_attribution(
    client: AsyncClient,
) -> None:
    org_id, _, post_ids = await _org_with_announcements(
        client, "feed-org", ["First", "Second"], "0912347101"
    )
    listed = await client.get("/announcements")
    assert listed.status_code == 200, listed.text
    page = listed.json()
    items = {item["id"]: item for item in page["items"]}
    assert post_ids[1] in items and post_ids[0] in items
    # Newest first: Second was posted after First.
    ids = [item["id"] for item in page["items"]]
    assert ids.index(post_ids[1]) < ids.index(post_ids[0])
    item = items[post_ids[1]]
    assert item["title"] == "Second"
    assert item["org"]["id"] == org_id
    assert item["org"]["slug"] == "feed-org"
    assert item["org"]["name"] == "Name feed-org"


async def test_timeline_excludes_everything_not_public(
    client: AsyncClient,
) -> None:
    org_id, owner_h, post_ids = await _org_with_announcements(
        client, "feed-hide", ["Live"], "0912347102"
    )
    discussion = await client.post(
        f"/orgs/{org_id}/posts",
        json={"kind": "discussion", "body": "internal"},
        headers=owner_h,
    )
    assert discussion.status_code == 201, discussion.text
    draft = await client.post(
        f"/orgs/{org_id}/posts",
        json={
            "kind": "announcement", "title": "D", "body": "b",
            "status": "draft",
        },
        headers=owner_h,
    )
    assert draft.status_code == 201, draft.text
    gone = await client.post(
        f"/orgs/{org_id}/posts/{post_ids[0]}/unpublish", headers=owner_h
    )
    assert gone.status_code == 200, gone.text

    listed = await client.get("/announcements")
    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json()["items"]}
    assert post_ids[0] not in ids
    assert discussion.json()["post_id"] not in ids
    assert draft.json()["post_id"] not in ids


async def test_timeline_paginates_by_cursor(client: AsyncClient) -> None:
    _, _, post_ids = await _org_with_announcements(
        client, "feed-page", ["One", "Two", "Three"], "0912347103"
    )
    first = await client.get("/announcements?limit=2")
    assert first.status_code == 200
    page_one = first.json()
    assert page_one["items"][0]["id"] == post_ids[2]
    assert page_one["next_cursor"] is not None
    second = await client.get(
        f"/announcements?limit=2&cursor={page_one['next_cursor']}"
    )
    assert second.status_code == 200
    page_two = second.json()
    remaining = {item["id"] for item in page_two["items"]}
    assert post_ids[0] in remaining
    assert post_ids[2] not in remaining
