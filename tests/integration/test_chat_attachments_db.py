"""Integration tests: staged chat attachments over HTTP."""

from __future__ import annotations

import base64

from httpx import AsyncClient

from tests.integration.test_workspace_db import _org_with_member

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


async def test_attachment_upload_then_send(client: AsyncClient) -> None:
    org_id, owner_h, member_h, _mid = await _org_with_member(
        client, "ws-attach"
    )

    uploaded = await client.post(
        f"/chat/rooms/{org_id}/attachments",
        files={"file": ("dot.png", _PNG, "image/png")},
        headers=member_h,
    )
    assert uploaded.status_code == 201, uploaded.text
    media_id = uploaded.json()["media_id"]
    assert uploaded.json()["url"].startswith("/media/")

    sent = await client.post(
        f"/chat/rooms/{org_id}/messages",
        json={"body": "", "attachment_ids": [media_id]},
        headers=member_h,
    )
    assert sent.status_code == 201, sent.text
    attachments = sent.json()["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["media_id"] == media_id
    assert attachments[0]["mime"].startswith("image/")

    # An empty text-only message is still rejected.
    empty = await client.post(
        f"/chat/rooms/{org_id}/messages",
        json={"body": "   "},
        headers=member_h,
    )
    assert empty.status_code == 400


async def test_attachment_discard_and_single_use_claim(
    client: AsyncClient,
) -> None:
    """One staged file: discardable while unsent, single-use on send."""
    org_id, owner_h, member_h, _mid = await _org_with_member(
        client, "ws-claim"
    )

    uploaded = await client.post(
        f"/chat/rooms/{org_id}/attachments",
        files={"file": ("one.png", _PNG, "image/png")},
        headers=member_h,
    )
    assert uploaded.status_code == 201, uploaded.text
    media_id = uploaded.json()["media_id"]
    url = uploaded.json()["url"]

    # Discarding a staged file deletes it; it can no longer be sent.
    dropped = await client.delete(
        f"/chat/rooms/{org_id}/attachments/{media_id}", headers=member_h
    )
    assert dropped.status_code == 204, dropped.text
    served = await client.get(url)
    assert served.status_code == 404
    again = await client.post(
        f"/chat/rooms/{org_id}/messages",
        json={"body": "", "attachment_ids": [media_id]},
        headers=member_h,
    )
    assert again.status_code == 404

    # A sent file is claimed: resending or discarding it is refused,
    # and only the message delete path frees the bytes.
    staged = await client.post(
        f"/chat/rooms/{org_id}/attachments",
        files={"file": ("two.png", _PNG, "image/png")},
        headers=member_h,
    )
    media_id = staged.json()["media_id"]
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
    claimed = await client.delete(
        f"/chat/rooms/{org_id}/attachments/{media_id}", headers=member_h
    )
    assert claimed.status_code == 403
    # Another room member cannot discard someone else's staged file.
    staged2 = await client.post(
        f"/chat/rooms/{org_id}/attachments",
        files={"file": ("three.png", _PNG, "image/png")},
        headers=member_h,
    )
    foreign = await client.delete(
        f"/chat/rooms/{org_id}/attachments/{staged2.json()['media_id']}",
        headers=owner_h,
    )
    assert foreign.status_code == 403
