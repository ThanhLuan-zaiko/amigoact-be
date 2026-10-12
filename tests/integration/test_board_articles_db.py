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
    assert trash.json()["items"][0]["deleted_at"] is not None

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
