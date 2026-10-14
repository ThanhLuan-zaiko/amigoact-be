"""Integration: article drafts, block media, publish, trash over HTTP."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_workspace_db import _org_with_member


async def _upload(
    client: AsyncClient, org_id: str, headers: dict[str, str], name: str,
    payload: bytes, mime: str,
) -> str:
    made = await client.post(
        f"/orgs/{org_id}/media",
        files={"file": (name, payload, mime)},
        data={"role": "attachment"},
        headers=headers,
    )
    assert made.status_code == 201, made.text
    return made.json()["id"]


async def test_article_lifecycle(client: AsyncClient) -> None:
    org_id, owner_h, member_h, _ = await _org_with_member(client, "ws-art")
    base = f"/orgs/{org_id}/posts"
    image = await _upload(
        client, org_id, member_h, "a.png", b"\x89PNG" + b"1" * 120,
        "image/png",
    )
    video = await _upload(
        client, org_id, member_h, "v.mp4", b"\x00\x00" + b"3" * 64,
        "video/mp4",
    )

    draft = await client.post(
        base,
        json={
            "status": "draft",
            "title": "My story",
            "blocks": [
                {"type": "paragraph", "text": "Intro"},
                {"type": "video", "asset_id": video, "caption": "Clip"},
            ],
        },
        headers=member_h,
    )
    assert draft.status_code == 201, draft.text
    post = draft.json()
    post_id = post["post_id"]
    assert post["status"] == "draft" and post["published_at"] is None
    assert [m["asset_id"] for m in post["media"]] == [video]

    feed = await client.get(base, headers=owner_h)
    assert feed.json()["items"] == []
    hidden = await client.get(f"{base}/{post_id}", headers=owner_h)
    assert hidden.status_code == 404
    drafts = await client.get(f"{base}/drafts", headers=member_h)
    assert drafts.status_code == 200
    assert [p["post_id"] for p in drafts.json()["items"]] == [post_id]

    edited = await client.patch(
        f"{base}/{post_id}",
        json={
            "title": "My story",
            "cover_media_id": image,
            "blocks": [
                {"type": "heading", "text": "Part 1", "level": 2},
                {"type": "image", "asset_id": image, "caption": "Pic"},
                {"type": "paragraph", "text": "Body"},
            ],
        },
        headers=member_h,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["cover_media_id"] == image
    assert edited.json()["media"][0]["file_url"].startswith("/media/")

    published = await client.post(f"{base}/{post_id}/publish", headers=member_h)
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    # Timestamps carry a UTC marker so clients render local time right.
    assert published.json()["published_at"].endswith("Z")
    again = await client.post(f"{base}/{post_id}/publish", headers=member_h)
    assert again.status_code == 400
    assert again.json()["code"] == "INVALID_POST_STATE"
    feed = await client.get(base, headers=owner_h)
    assert [p["post_id"] for p in feed.json()["items"]] == [post_id]
    assert feed.json()["items"][0]["blocks"][0]["text"] == "Part 1"
    assert feed.json()["total"] == 1
    deep = await client.get(f"{base}?page=2", headers=owner_h)
    assert deep.status_code == 200 and deep.json()["items"] == []

    trashed = await client.delete(f"{base}/{post_id}", headers=owner_h)
    assert trashed.status_code == 204
    assert (await client.get(f"{base}/{post_id}", headers=member_h)).status_code == 404
    trash = await client.get(f"{base}/trash", headers=owner_h)
    assert [p["post_id"] for p in trash.json()["items"]] == [post_id]
    assert trash.json()["items"][0]["deleted_at"].endswith("Z")

    restored = await client.post(f"{base}/{post_id}/restore", headers=member_h)
    assert restored.status_code == 200, restored.text
    assert restored.json()["deleted_at"] is None
    feed = await client.get(base, headers=member_h)
    assert [p["post_id"] for p in feed.json()["items"]] == [post_id]

    purged = await client.delete(f"{base}/{post_id}?hard=true", headers=member_h)
    assert purged.status_code == 204
    gone = await client.post(f"{base}/{post_id}/restore", headers=member_h)
    assert gone.status_code == 404
    assert (await client.get(f"{base}/trash", headers=owner_h)).json()["items"] == []


async def test_revision_round_trip_keeps_one_board_entry(
    client: AsyncClient,
) -> None:
    """Editing a live post goes through a private revision draft; publish
    folds it back so the feed keeps a single entry (same post_id)."""
    org_id, owner_h, member_h, _ = await _org_with_member(client, "ws-rev")
    base = f"/orgs/{org_id}/posts"
    made = await client.post(
        base, json={"title": "Live", "body": "v1"}, headers=member_h
    )
    assert made.status_code == 201, made.text
    post_id = made.json()["post_id"]

    rev = await client.post(f"{base}/{post_id}/revisions", headers=member_h)
    assert rev.status_code == 200, rev.text
    rev_id = rev.json()["post_id"]
    assert rev_id != post_id
    assert rev.json()["revision_of"] == post_id
    assert rev.json()["status"] == "draft"
    again = await client.post(f"{base}/{post_id}/revisions", headers=member_h)
    assert again.json()["post_id"] == rev_id  # idempotent, no duplicates

    edited = await client.patch(
        f"{base}/{rev_id}",
        json={"title": "Live v2", "body": "v2"},
        headers=member_h,
    )
    assert edited.status_code == 200, edited.text
    assert (await client.get(base, headers=owner_h)).json()["items"][0][
        "body"
    ] == "v1"  # the live version is untouched while the draft sits

    merged = await client.post(f"{base}/{rev_id}/publish", headers=member_h)
    assert merged.status_code == 200, merged.text
    assert merged.json()["post_id"] == post_id
    assert merged.json()["body"] == "v2"
    assert merged.json()["revision_of"] is None
    feed = await client.get(base, headers=owner_h)
    assert [p["post_id"] for p in feed.json()["items"]] == [post_id]
    assert feed.json()["items"][0]["body"] == "v2"
    drafts = await client.get(f"{base}/drafts", headers=member_h)
    assert drafts.json()["items"] == []


async def test_trash_cascades_to_open_revision(client: AsyncClient) -> None:
    org_id, owner_h, member_h, _ = await _org_with_member(client, "ws-rev2")
    base = f"/orgs/{org_id}/posts"
    made = await client.post(base, json={"body": "v1"}, headers=member_h)
    post_id = made.json()["post_id"]
    rev = await client.post(f"{base}/{post_id}/revisions", headers=member_h)
    rev_id = rev.json()["post_id"]
    denied = await client.post(f"{base}/{post_id}/revisions", headers=owner_h)
    assert denied.status_code == 403  # only the author stages edits
    assert (
        await client.delete(f"{base}/{post_id}", headers=member_h)
    ).status_code == 204
    trash = await client.get(f"{base}/trash", headers=member_h)
    assert {p["post_id"] for p in trash.json()["items"]} == {post_id, rev_id}


async def test_unpublish_and_trash_permissions(client: AsyncClient) -> None:
    org_id, owner_h, member_h, _ = await _org_with_member(client, "ws-art2")
    base = f"/orgs/{org_id}/posts"
    made = await client.post(
        base, json={"title": "Hi", "body": "Plain"}, headers=owner_h
    )
    post_id = made.json()["post_id"]
    denied = await client.delete(f"{base}/{post_id}", headers=member_h)
    assert denied.status_code == 403
    denied_hard = await client.delete(
        f"{base}/{post_id}?hard=true", headers=member_h
    )
    assert denied_hard.status_code == 403
    back = await client.post(f"{base}/{post_id}/unpublish", headers=owner_h)
    assert back.status_code == 200
    assert back.json()["status"] == "draft"
    assert (await client.get(base, headers=member_h)).json()["items"] == []
    empty = await client.post(base, json={"status": "draft"}, headers=owner_h)
    assert empty.status_code == 422


async def test_public_announcements_guest_surface(client: AsyncClient) -> None:
    """Guests read published announcements on the org profile; drafts,
    revisions, discussions and trash never leave the member board."""
    slug = "ws-pub"
    org_id, owner_h, member_h, _ = await _org_with_member(client, slug)
    base = f"/orgs/{org_id}/posts"
    announcement = await client.post(
        base,
        json={
            "kind": "announcement",
            "title": "Relief round 3",
            "body": "Public content.",
        },
        headers=owner_h,
    )
    assert announcement.status_code == 201, announcement.text
    post_id = announcement.json()["post_id"]
    await client.post(
        base, json={"kind": "discussion", "body": "internal"}, headers=member_h
    )
    draft = await client.post(
        base,
        json={"kind": "announcement", "status": "draft", "body": "pending"},
        headers=owner_h,
    )
    draft_id = draft.json()["post_id"]

    profile = await client.get(f"/orgs/{slug}")  # no auth header at all
    assert profile.status_code == 200
    body = profile.json()
    assert body["announcement_count"] == 1
    assert [a["id"] for a in body["announcements"]] == [post_id]
    assert body["announcements"][0]["title"] == "Relief round 3"
    assert body["announcements"][0]["author_name"]
    assert body["announcements"][0]["published_at"].endswith("Z")

    public = await client.get(f"/orgs/{slug}/announcements/{post_id}")
    assert public.status_code == 200
    assert public.json()["body"] == "Public content."
    assert public.json()["status"] == "published"
    assert public.json()["deleted_at"] is None
    for hidden in (draft_id, "00000000-0000-7000-8000-000000000000"):
        assert (
            await client.get(f"/orgs/{slug}/announcements/{hidden}")
        ).status_code == 404

    listing = await client.get(f"/orgs/{slug}/announcements")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert [a["id"] for a in listing.json()["items"]] == [post_id]
    missing = await client.get("/orgs/no-such-org/announcements")
    assert missing.status_code == 404
    stray = await client.get(f"/orgs/{slug}/announcements?page=abc")
    assert stray.status_code == 422

    trashed = await client.delete(f"{base}/{post_id}", headers=owner_h)
    assert trashed.status_code == 204
    assert (
        await client.get(f"/orgs/{slug}/announcements/{post_id}")
    ).status_code == 404
    profile = await client.get(f"/orgs/{slug}")
    assert profile.json()["announcements"] == []
