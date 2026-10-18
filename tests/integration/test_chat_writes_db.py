"""Integration tests: reply, edit and attachment endpoints over HTTP."""

from __future__ import annotations

import base64

from httpx import AsyncClient

from tests.integration.test_workspace_db import (
    _headers,
    _org_with_member,
    _token,
)

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


async def test_reply_and_edit_roundtrip(client: AsyncClient) -> None:
    org_id, owner_h, member_h, _mid = await _org_with_member(
        client, "ws-write"
    )

    sent = await client.post(
        f"/chat/rooms/{org_id}/messages",
        json={"body": "tin g\u1ED1c"},
        headers=owner_h,
    )
    assert sent.status_code == 201, sent.text
    message_id = sent.json()["message_id"]

    replied = await client.post(
        f"/chat/rooms/{org_id}/messages",
        json={"body": "\u0111\u1ED3ng \u00FD", "reply_to_id": message_id},
        headers=member_h,
    )
    assert replied.status_code == 201, replied.text
    assert replied.json()["reply_to_id"] == message_id
    assert replied.json()["reply_to_body"] == "tin g\u1ED1c"
    assert replied.json()["reply_to_author"]

    edited = await client.patch(
        f"/chat/rooms/{org_id}/messages/{message_id}",
        json={"body": "tin \u0111\u00E3 s\u1EEDa"},
        headers=owner_h,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["body"] == "tin \u0111\u00E3 s\u1EEDa"
    assert edited.json()["edited_at"] is not None

    # Another member cannot rewrite the owner's message.
    denied = await client.patch(
        f"/chat/rooms/{org_id}/messages/{message_id}",
        json={"body": "chi\u1EBFm \u0111o\u1EA1t"},
        headers=member_h,
    )
    assert denied.status_code == 403

    page = await client.get(
        f"/chat/rooms/{org_id}/messages", headers=owner_h
    )
    items = {m["message_id"]: m for m in page.json()["items"]}
    assert items[message_id]["body"] == "tin \u0111\u00E3 s\u1EEDa"
    assert items[replied.json()["message_id"]]["reply_to_id"] == message_id


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


async def test_reactions_mentions_and_encrypted_body(
    client: AsyncClient,
) -> None:
    """Phase 2: emoji toggles, mention fan-out, ciphertext at rest."""
    org_id, owner_h, member_h, member_id = await _org_with_member(
        client, "ws-react"
    )

    sent = await client.post(
        f"/chat/rooms/{org_id}/messages",
        json={"body": "hi"},
        headers=owner_h,
    )
    message_id = sent.json()["message_id"]

    reacted = await client.put(
        f"/chat/rooms/{org_id}/messages/{message_id}/reactions",
        json={"emoji": "\U0001F44D"},
        headers=member_h,
    )
    assert reacted.status_code == 200, reacted.text
    assert reacted.json()["reactions"] == [
        {"emoji": "\U0001F44D", "count": 1, "mine": True}
    ]
    again = await client.put(
        f"/chat/rooms/{org_id}/messages/{message_id}/reactions",
        json={"emoji": "\U0001F44D"},
        headers=member_h,
    )
    assert again.json()["reactions"] == []

    bad = await client.put(
        f"/chat/rooms/{org_id}/messages/{message_id}/reactions",
        json={"emoji": "\U0001F984"},
        headers=member_h,
    )
    assert bad.status_code in (400, 409)

    # Mentions: an @name against the owner's display name notifies them.
    from auth.model import User
    from orgs.model import Organization
    org = Organization.objects(id=org_id).first()
    owner = User.objects(id=org.owner_id).first() if org else None
    owner_name = owner.full_name if owner is not None else ""
    if owner_name:
        ping = await client.post(
            f"/chat/rooms/{org_id}/messages",
            json={"body": f"ch\u00E0o @{owner_name}"},
            headers=member_h,
        )
        assert ping.status_code == 201, ping.text
        assert [m["user_id"] for m in ping.json()["mentions"]]

    # At rest the stored body is ciphertext; the API returns plaintext.
    from chat.model import OrgRoomMessage
    row = OrgRoomMessage.objects(
        room_id=org_id, bucket=__import__('chat.helpers', fromlist=['x']).bucket_of_uuid(__import__('uuid').UUID(message_id)), message_id=__import__('uuid').UUID(message_id)
    ).first()
    assert row is not None and row.body.startswith("v1gcm:")


async def test_pin_and_mute_roundtrip(
    client: AsyncClient,
) -> None:
    """Pin needs chat:manage/owner; mutes are per-user and inbox-flagged."""
    org_id, owner_h, member_h, _ = await _org_with_member(
        client, "chat-p3"
    )
    sent = await client.post(
        f"/chat/rooms/{org_id}/messages",
        json={"body": "pin me"},
        headers=owner_h,
    )
    message_id = sent.json()["message_id"]
    sent2 = await client.post(
        f"/chat/rooms/{org_id}/messages",
        json={"body": "pin me too"},
        headers=owner_h,
    )
    message_id2 = sent2.json()["message_id"]

    denied = await client.put(
        f"/chat/rooms/{org_id}/pins/{message_id}",
        headers=member_h,
    )
    assert denied.status_code in (403, 404)

    pinned = await client.put(
        f"/chat/rooms/{org_id}/pins/{message_id}",
        headers=owner_h,
    )
    assert pinned.status_code == 204
    pinned2 = await client.put(
        f"/chat/rooms/{org_id}/pins/{message_id2}",
        headers=owner_h,
    )
    assert pinned2.status_code == 204
    page = await client.get(
        f"/chat/rooms/{org_id}/messages", headers=member_h
    )
    assert [p["message_id"] for p in page.json()["pinned"]] == [
        message_id, message_id2
    ]

    unpinned = await client.delete(
        f"/chat/rooms/{org_id}/pins/{message_id}", headers=owner_h
    )
    assert unpinned.status_code == 204
    page2 = await client.get(
        f"/chat/rooms/{org_id}/messages", headers=member_h
    )
    assert [p["message_id"] for p in page2.json()["pinned"]] == [
        message_id2
    ]

    muted = await client.put(
        f"/chat/rooms/{org_id}/mute", headers=member_h
    )
    assert muted.status_code == 204
    page3 = await client.get(
        f"/chat/rooms/{org_id}/messages", headers=member_h
    )
    assert page3.json()["muted"] is True
    inbox = await client.get("/chat/inbox", headers=member_h)
    row = next(
        item for item in inbox.json()["items"]
        if item["room_id"] == org_id
    )
    assert row["muted"] is True
    unmuted = await client.delete(
        f"/chat/rooms/{org_id}/mute", headers=member_h
    )
    assert unmuted.status_code == 204


async def test_room_reads_list_member_pointers(
    client: AsyncClient,
) -> None:
    """GET /chat/rooms/{id}/reads: the sender's group seen-by list."""
    org_id, owner_h, member_h, member_id = await _org_with_member(
        client, "ws-reads"
    )
    sent = await client.post(
        f"/chat/rooms/{org_id}/messages",
        json={"body": "seen?"},
        headers=owner_h,
    )
    assert sent.status_code == 201, sent.text
    message_id = sent.json()["message_id"]

    marked = await client.post(
        f"/chat/rooms/{org_id}/read",
        json={"message_id": message_id},
        headers=member_h,
    )
    assert marked.status_code == 200, marked.text

    reads = await client.get(
        f"/chat/rooms/{org_id}/reads", headers=owner_h
    )
    assert reads.status_code == 200, reads.text
    items = {row["user_id"]: row for row in reads.json()["items"]}
    assert member_id in items
    assert items[member_id]["last_read_message_id"] == message_id
    assert items[member_id]["last_read_at"] is not None
    assert items[member_id]["user_name"]

    stranger = await _token(client, "ws-reads-out@x.com", "0912347005")
    denied = await client.get(
        f"/chat/rooms/{org_id}/reads", headers=_headers(stranger)
    )
    assert denied.status_code == 403


async def test_message_carries_author_avatar_url(client: AsyncClient) -> None:
    """Send response and history rows expose the author's avatar URL."""
    org_id, owner_h, member_h, _mid = await _org_with_member(
        client, "ws-ava"
    )
    uploaded = await client.post(
        "/profiles/me/avatar",
        files={"file": ("me.png", _PNG, "image/png")},
        headers=member_h,
    )
    assert uploaded.status_code == 200, uploaded.text
    sent = await client.post(
        f"/chat/rooms/{org_id}/messages",
        json={"body": "c\u00F3 avatar"},
        headers=member_h,
    )
    assert sent.status_code == 201, sent.text
    assert sent.json()["author_avatar_url"] == uploaded.json()["avatar_url"]
    page = await client.get(
        f"/chat/rooms/{org_id}/messages", headers=owner_h
    )
    mine = next(
        m
        for m in page.json()["items"]
        if m["message_id"] == sent.json()["message_id"]
    )
    assert mine["author_avatar_url"] == uploaded.json()["avatar_url"]
