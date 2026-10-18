"""Integration: chat and board files never leak into the org gallery (HTTP)."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_workspace_db import _headers, _org_with_member, _token

PNG = b"\x89PNG" + b"1" * 200
OTHER_PNG = b"\x89PNG" + b"2" * 200


async def _stage(client: AsyncClient, org_id: str, headers: dict, payload: bytes) -> dict:
    staged = await client.post(
        f"/chat/rooms/{org_id}/attachments",
        files={"file": ("c.png", payload, "image/png")},
        headers=headers,
    )
    assert staged.status_code == 201, staged.text
    return staged.json()


async def test_chat_files_stay_out_of_gallery_and_gallery_ops(
    client: AsyncClient,
) -> None:
    org_id, owner_h, member_h, _ = await _org_with_member(client, "own-gal")
    gallery = await client.post(
        f"/orgs/{org_id}/media",
        files={"file": ("g.png", PNG, "image/png")},
        headers=owner_h,
    )
    assert gallery.status_code == 201, gallery.text
    gallery_id = gallery.json()["id"]
    gallery_url = gallery.json()["file_url"]

    sent_file = await _stage(client, org_id, member_h, PNG)
    sent = await client.post(
        f"/chat/rooms/{org_id}/messages",
        json={"body": "", "attachment_ids": [sent_file["media_id"]]},
        headers=member_h,
    )
    assert sent.status_code == 201, sent.text
    staged_file = await _stage(client, org_id, member_h, OTHER_PNG)
    chat_urls = [sent_file["url"], staged_file["url"]]

    listed = await client.get(f"/orgs/{org_id}/media", headers=owner_h)
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == [gallery_id]

    slug = "own-gal"
    public_reads = [
        await client.get(f"/orgs/{slug}/gallery"),
        await client.get(f"/orgs/{slug}"),
        await client.get("/orgs"),
    ]
    for response in public_reads:
        assert response.status_code == 200, response.text
        for url in chat_urls:
            assert url not in response.text
    assert gallery_url in public_reads[0].text

    for media_id in (sent_file["media_id"], staged_file["media_id"]):
        patched = await client.patch(
            f"/orgs/{org_id}/media/{media_id}",
            json={"role": "cover"},
            headers=owner_h,
        )
        assert patched.status_code == 404, patched.text
        replaced = await client.put(
            f"/orgs/{org_id}/media/{media_id}/file",
            files={"file": ("x.png", OTHER_PNG, "image/png")},
            headers=owner_h,
        )
        assert replaced.status_code == 404, replaced.text
        removed = await client.delete(
            f"/orgs/{org_id}/media/{media_id}", headers=owner_h
        )
        assert removed.status_code == 404, removed.text

    wiped = await client.delete(f"/orgs/{org_id}/media", headers=owner_h)
    assert wiped.status_code == 204, wiped.text
    assert (await client.get(f"/orgs/{org_id}/media", headers=owner_h)).json() == []
    for url in chat_urls:
        served = await client.get(url)
        assert served.status_code == 200, url


async def test_deleting_message_removes_its_file(client: AsyncClient) -> None:
    org_id, _owner_h, member_h, _ = await _org_with_member(client, "own-del")
    staged = await _stage(client, org_id, member_h, PNG)
    sent = await client.post(
        f"/chat/rooms/{org_id}/messages",
        json={"body": "", "attachment_ids": [staged["media_id"]]},
        headers=member_h,
    )
    assert sent.status_code == 201, sent.text
    assert (await client.get(staged["url"])).status_code == 200

    deleted = await client.delete(
        f"/chat/rooms/{org_id}/messages/{sent.json()['message_id']}",
        headers=member_h,
    )
    assert deleted.status_code == 204, deleted.text
    assert (await client.get(staged["url"])).status_code == 404


async def test_board_uploads_are_post_media_not_gallery(client: AsyncClient) -> None:
    org_id, owner_h, member_h, _ = await _org_with_member(client, "own-board")
    base = f"/orgs/{org_id}/posts"

    cover = await client.post(
        f"{base}/media",
        files={"file": ("c.png", PNG, "image/png")},
        headers=member_h,
    )
    assert cover.status_code == 201, cover.text
    block = await client.post(
        f"{base}/media",
        files={"file": ("b.png", OTHER_PNG, "image/png")},
        headers=member_h,
    )
    assert block.status_code == 201, block.text
    assert (await client.get(f"/orgs/{org_id}/media", headers=owner_h)).json() == []

    created = await client.post(
        base,
        json={
            "kind": "announcement",
            "title": "Board",
            "body": "b",
            "cover_media_id": cover.json()["id"],
            "blocks": [
                {"type": "image", "asset_id": block.json()["id"], "caption": ""}
            ],
        },
        headers=owner_h,
    )
    assert created.status_code == 201, created.text

    chat_file = await _stage(client, org_id, member_h, PNG)
    rejected = await client.post(
        base,
        json={
            "kind": "announcement",
            "title": "Chat cover",
            "body": "b",
            "cover_media_id": chat_file["media_id"],
            "blocks": [],
        },
        headers=owner_h,
    )
    assert rejected.status_code == 404, rejected.text


async def test_gallery_rejects_attachment_role_and_outsiders_cannot_post_media(
    client: AsyncClient,
) -> None:
    org_id, owner_h, _member_h, _ = await _org_with_member(client, "own-role")
    as_attachment = await client.post(
        f"/orgs/{org_id}/media",
        files={"file": ("a.png", PNG, "image/png")},
        data={"role": "attachment"},
        headers=owner_h,
    )
    assert as_attachment.status_code == 400, as_attachment.text
    assert as_attachment.json()["code"] == "INVALID_MEDIA_ROLE"

    outsider = await _token(client, "own-role-out@x.com", "0912347091")
    denied = await client.post(
        f"/orgs/{org_id}/posts/media",
        files={"file": ("a.png", PNG, "image/png")},
        headers=_headers(outsider),
    )
    assert denied.status_code == 403, denied.text
