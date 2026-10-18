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


async def test_timeline_carries_author_avatar_url(client: AsyncClient) -> None:
    owner = await _token(client, "feed-ava-own@x.com", "0912347104")
    owner_h = _headers(owner)
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\x0bIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
        b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    uploaded = await client.post(
        "/profiles/me/avatar",
        files={"file": ("me.png", png, "image/png")},
        headers=owner_h,
    )
    assert uploaded.status_code == 200, uploaded.text
    created = await client.post(
        "/orgs",
        json={
            "name": "Name feed-ava",
            "slug": "feed-ava",
            "description": "D",
            "kind": "club",
            "join_policy": "invite",
        },
        headers=owner_h,
    )
    assert created.status_code == 201, created.text
    made = await client.post(
        f"/orgs/{created.json()['id']}/posts",
        json={"kind": "announcement", "title": "Hi", "body": "b"},
        headers=owner_h,
    )
    assert made.status_code == 201, made.text

    listed = await client.get("/announcements")
    assert listed.status_code == 200, listed.text
    item = next(
        row
        for row in listed.json()["items"]
        if row["id"] == made.json()["post_id"]
    )
    assert item["author_name"] == "Feed User"
    assert item["author_avatar_url"] == uploaded.json()["avatar_url"]


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


async def test_post_media_endpoint_lists_everything_cover_first(
    client: AsyncClient,
) -> None:
    """GET /orgs/{slug}/announcements/{id}/media feeds the lightbox:
    every attachment, cover first, guest-readable; member posts 404."""
    org_id, owner_h, _ = await _org_with_announcements(
        client, "feed-med", ["Warmup"], "0912347105"
    )
    png = b"\x89PNG" + b"4" * 120

    async def upload(name: str, payload: bytes, mime: str) -> str:
        made = await client.post(
            f"/orgs/{org_id}/posts/media",
            files={"file": (name, payload, mime)},
            headers=owner_h,
        )
        assert made.status_code == 201, made.text
        return made.json()["id"]

    images = [await upload(f"i{i}.png", png, "image/png") for i in range(3)]
    clip = await upload("v.mp4", b"\x00\x00" + b"3" * 64, "video/mp4")
    cover = await upload("c.png", png, "image/png")

    made = await client.post(
        f"/orgs/{org_id}/posts",
        json={
            "kind": "announcement",
            "title": "Media",
            "body": "b",
            "cover_media_id": cover,
            "blocks": [
                *[
                    {"type": "image", "asset_id": a, "caption": ""}
                    for a in images
                ],
                {"type": "video", "asset_id": clip, "caption": ""},
            ],
        },
        headers=owner_h,
    )
    assert made.status_code == 201, made.text
    post_id = made.json()["post_id"]
    url_by_id = {
        m["asset_id"]: m["file_url"] for m in made.json()["media"]
    }

    listed = await client.get(
        f"/orgs/feed-med/announcements/{post_id}/media"
    )  # guest: no auth
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert set(body.keys()) == {"items"}
    urls = [item["url"] for item in body["items"]]
    assert urls[0] == url_by_id[cover]
    assert len(urls) == 5  # cover + 3 image blocks + 1 video block
    for tile in body["items"]:
        assert set(tile.keys()) == {"url", "kind", "mime"}

    member_only = await client.post(
        f"/orgs/{org_id}/posts",
        json={
            "kind": "announcement", "title": "Secret", "body": "b",
            "visibility": "members",
        },
        headers=owner_h,
    )
    assert member_only.status_code == 201, member_only.text
    blocked = await client.get(
        f"/orgs/feed-med/announcements/"
        f"{member_only.json()['post_id']}/media"
    )
    assert blocked.status_code == 404
    from core.ids import uuid7

    missing = await client.get(
        f"/orgs/feed-med/announcements/{uuid7()}/media"
    )
    assert missing.status_code == 404


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
