"""Regression: chat/board files stay out of the org gallery; board upload shape."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_workspace_db import _org_with_member

PNG = b"\x89PNG" + b"1" * 200
OTHER_PNG = b"\x89PNG" + b"2" * 200


async def test_chat_attachment_leaked_into_org_gallery_after_second_chat_upload(
    client: AsyncClient,
) -> None:
    """Case: every new chat upload demoted earlier attachments to gallery,
    so chat images showed up on /manage/orgs and the public org pages."""
    org_id, owner_h, member_h, _ = await _org_with_member(client, "reg-leak")
    urls: list[str] = []
    for payload in (PNG, OTHER_PNG):
        staged = await client.post(
            f"/chat/rooms/{org_id}/attachments",
            files={"file": ("c.png", payload, "image/png")},
            headers=member_h,
        )
        assert staged.status_code == 201, staged.text
        sent = await client.post(
            f"/chat/rooms/{org_id}/messages",
            json={"body": "", "attachment_ids": [staged.json()["media_id"]]},
            headers=member_h,
        )
        assert sent.status_code == 201, sent.text
        urls.append(staged.json()["url"])

    manage = await client.get(f"/orgs/{org_id}/media", headers=owner_h)
    assert manage.status_code == 200, manage.text
    assert manage.json() == []
    gallery = await client.get("/orgs/reg-leak/gallery")
    assert gallery.status_code == 200, gallery.text
    assert gallery.json()["items"] == []
    public = await client.get("/orgs")
    assert public.status_code == 200, public.text
    for url in urls:
        assert url not in gallery.text
        assert url not in public.text

    wiped = await client.delete(f"/orgs/{org_id}/media", headers=owner_h)
    assert wiped.status_code == 204, wiped.text
    for url in urls:
        served = await client.get(url)
        assert served.status_code == 200, url
        assert served.content in (PNG, OTHER_PNG)


async def test_board_upload_response_shape_is_frozen(client: AsyncClient) -> None:
    org_id, owner_h, _member_h, _ = await _org_with_member(client, "reg-shape")
    uploaded = await client.post(
        f"/orgs/{org_id}/posts/media",
        files={"file": ("b.png", PNG, "image/png")},
        headers=owner_h,
    )
    assert uploaded.status_code == 201, uploaded.text
    assert set(uploaded.json().keys()) == {
        "id",
        "org_id",
        "kind",
        "mime",
        "size_bytes",
        "file_url",
        "original_name",
    }


async def test_gallery_upload_with_attachment_role_is_invalid(
    client: AsyncClient,
) -> None:
    org_id, owner_h, _member_h, _ = await _org_with_member(client, "reg-role")
    rejected = await client.post(
        f"/orgs/{org_id}/media",
        files={"file": ("a.png", PNG, "image/png")},
        data={"role": "attachment"},
        headers=owner_h,
    )
    assert rejected.status_code == 400, rejected.text
    assert rejected.json()["code"] == "INVALID_MEDIA_ROLE"


async def test_staged_chat_file_single_use_and_disappear_on_chip_discard(
    client: AsyncClient,
) -> None:
    """Case: one staged file could be attached to many messages (a
    delete wiped bytes the survivors still rendered), and abandoned
    chips lived forever in storage. Now a file claims exactly one
    message, chips are discardable, and discard removes bytes."""
    org_id, _owner_h, member_h, _ = await _org_with_member(
        client, "reg-claim"
    )
    staged = await client.post(
        f"/chat/rooms/{org_id}/attachments",
        files={"file": ("c.png", PNG, "image/png")},
        headers=member_h,
    )
    assert staged.status_code == 201, staged.text
    media_id, url = staged.json()["media_id"], staged.json()["url"]

    sent = await client.post(
        f"/chat/rooms/{org_id}/messages",
        json={"body": "", "attachment_ids": [media_id]},
        headers=member_h,
    )
    assert sent.status_code == 201, sent.text
    resent = await client.post(
        f"/chat/rooms/{org_id}/messages",
        json={"body": "", "attachment_ids": [media_id]},
        headers=member_h,
    )
    assert resent.status_code == 403

    deleted = await client.delete(
        f"/chat/rooms/{org_id}/messages/{sent.json()['message_id']}",
        headers=member_h,
    )
    assert deleted.status_code == 204
    assert (await client.get(url)).status_code == 404

    abandoned = await client.post(
        f"/chat/rooms/{org_id}/attachments",
        files={"file": ("d.png", OTHER_PNG, "image/png")},
        headers=member_h,
    )
    dropped = await client.delete(
        f"/chat/rooms/{org_id}/attachments"
        f"/{abandoned.json()['media_id']}",
        headers=member_h,
    )
    assert dropped.status_code == 204
    gone = await client.get(abandoned.json()["url"])
    assert gone.status_code == 404
