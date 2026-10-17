"""Integration tests: named channel endpoints + room gates over HTTP."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_workspace_db import (
    _headers,
    _org_with_member,
    _token,
)


async def _grant_manage(
    client: AsyncClient, org_id: str, owner_h: dict, member_id: str
) -> None:
    """Give one member the chat:manage permission via a custom role."""
    role = await client.post(
        f"/orgs/{org_id}/roles",
        json={"name": "Chat Ops", "permissions": ["chat:manage"]},
        headers=owner_h,
    )
    assert role.status_code == 201, role.text
    patched = await client.patch(
        f"/orgs/{org_id}/members/{member_id}",
        json={"roles": ["Chat Ops"]},
        headers=owner_h,
    )
    assert patched.status_code == 200, patched.text


async def test_channel_crud_and_room_flow(client: AsyncClient) -> None:
    org_id, owner_h, member_h, _ = await _org_with_member(
        client, "chan-basic"
    )
    created = await client.post(
        f"/orgs/{org_id}/chat/channels",
        json={
            "name": "Bao cao tuan",
            "topic": "Weekly reports",
            "kind": "report",
        },
        headers=owner_h,
    )
    assert created.status_code == 201, created.text
    channel = created.json()
    cid = channel["channel_id"]
    assert channel["kind"] == "report"
    assert channel["post_policy"] == "everyone"
    assert channel["visibility"] == "org"

    # Members create channels? No - managers only.
    denied = await client.post(
        f"/orgs/{org_id}/chat/channels",
        json={"name": "sneaky"},
        headers=member_h,
    )
    assert denied.status_code == 403

    # The channel id doubles as the room id on every room endpoint.
    sent = await client.post(
        f"/chat/rooms/{cid}/messages",
        json={"body": "report xin"},
        headers=member_h,
    )
    assert sent.status_code == 201, sent.text
    page = await client.get(
        f"/chat/rooms/{cid}/messages", headers=member_h
    )
    assert page.json()["items"][0]["body"] == "report xin"

    # Inbox surfaces the channel row for both members.
    inbox = await client.get("/chat/inbox", headers=member_h)
    row = next(
        item for item in inbox.json()["items"] if item["room_id"] == cid
    )
    assert row["kind"] == "channel"
    assert row["title"] == "Bao cao tuan"
    assert row["channel_kind"] == "report"
    assert row["last_body"] == "report xin"


async def test_channel_name_conflict_and_rename(
    client: AsyncClient,
) -> None:
    org_id, owner_h, _mh, _ = await _org_with_member(client, "chan-name")
    first = await client.post(
        f"/orgs/{org_id}/chat/channels",
        json={"name": "General Ops"},
        headers=owner_h,
    )
    assert first.status_code == 201, first.text
    dup = await client.post(
        f"/orgs/{org_id}/chat/channels",
        json={"name": "general ops"},
        headers=owner_h,
    )
    assert (dup.status_code, dup.json()["code"]) == (
        409,
        "CHANNEL_NAME_TAKEN",
    )

    # Rename frees the old folded name for a new channel.
    renamed = await client.patch(
        f"/orgs/{org_id}/chat/channels/{first.json()['channel_id']}",
        json={"name": "Ops Room", "topic": "All ops"},
        headers=owner_h,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Ops Room"
    reuse = await client.post(
        f"/orgs/{org_id}/chat/channels",
        json={"name": "General Ops"},
        headers=owner_h,
    )
    assert reuse.status_code == 201, reuse.text


async def test_post_policy_managers_gate(client: AsyncClient) -> None:
    org_id, owner_h, member_h, member_id = await _org_with_member(
        client, "chan-policy"
    )
    created = await client.post(
        f"/orgs/{org_id}/chat/channels",
        json={"name": "announce", "post_policy": "managers"},
        headers=owner_h,
    )
    cid = created.json()["channel_id"]

    denied = await client.post(
        f"/chat/rooms/{cid}/messages",
        json={"body": "member post"},
        headers=member_h,
    )
    assert denied.status_code == 403
    posted = await client.post(
        f"/chat/rooms/{cid}/messages",
        json={"body": "owner post"},
        headers=owner_h,
    )
    assert posted.status_code == 201, posted.text

    # A chat:manage role unlocks posting for a regular member.
    await _grant_manage(client, org_id, owner_h, member_id)
    allowed = await client.post(
        f"/chat/rooms/{cid}/messages",
        json={"body": "manager post"},
        headers=member_h,
    )
    assert allowed.status_code == 201, allowed.text


async def test_restricted_channel_seats(client: AsyncClient) -> None:
    org_id, owner_h, member_h, member_id = await _org_with_member(
        client, "chan-restrict"
    )
    created = await client.post(
        f"/orgs/{org_id}/chat/channels",
        json={"name": "core team", "visibility": "restricted"},
        headers=owner_h,
    )
    assert created.status_code == 201, created.text
    cid = created.json()["channel_id"]

    # Unseated member: no room access, no roster, hidden from lists.
    denied = await client.get(
        f"/chat/rooms/{cid}/messages", headers=member_h
    )
    assert denied.status_code == 403
    listed = await client.get(
        f"/orgs/{org_id}/chat/channels", headers=member_h
    )
    assert listed.json()["items"] == []

    seat = await client.post(
        f"/orgs/{org_id}/chat/channels/{cid}/members",
        json={"user_id": member_id},
        headers=owner_h,
    )
    assert seat.status_code == 201, seat.text
    roster = await client.get(
        f"/orgs/{org_id}/chat/channels/{cid}/members",
        headers=owner_h,
    )
    assert member_id in {
        row["user_id"] for row in roster.json()["items"]
    }

    page = await client.get(
        f"/chat/rooms/{cid}/messages", headers=member_h
    )
    assert page.status_code == 200, page.text
    listed = await client.get(
        f"/orgs/{org_id}/chat/channels", headers=member_h
    )
    assert [row["channel_id"] for row in listed.json()["items"]] == [cid]

    revoked = await client.delete(
        f"/orgs/{org_id}/chat/channels/{cid}/members/{member_id}",
        headers=owner_h,
    )
    assert revoked.status_code == 204
    denied = await client.get(
        f"/chat/rooms/{cid}/messages", headers=member_h
    )
    assert denied.status_code == 403


async def test_archived_channel_freezes_writes(
    client: AsyncClient,
) -> None:
    org_id, owner_h, member_h, _ = await _org_with_member(
        client, "chan-arch"
    )
    created = await client.post(
        f"/orgs/{org_id}/chat/channels",
        json={"name": "legacy"},
        headers=owner_h,
    )
    cid = created.json()["channel_id"]
    sent = await client.post(
        f"/chat/rooms/{cid}/messages",
        json={"body": "before archive"},
        headers=owner_h,
    )
    message_id = sent.json()["message_id"]

    archived = await client.patch(
        f"/orgs/{org_id}/chat/channels/{cid}",
        json={"archived": True},
        headers=owner_h,
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived_at"] is not None

    for payload in (
        {"body": "post"},
    ):
        blocked = await client.post(
            f"/chat/rooms/{cid}/messages",
            json=payload,
            headers=owner_h,
        )
        assert (blocked.status_code, blocked.json()["code"]) == (
            409,
            "CHANNEL_ARCHIVED",
        )
    edited = await client.patch(
        f"/chat/rooms/{cid}/messages/{message_id}",
        json={"body": "rewrite"},
        headers=owner_h,
    )
    assert edited.status_code == 409
    reacted = await client.put(
        f"/chat/rooms/{cid}/messages/{message_id}/reactions",
        json={"emoji": "\U0001f44d"},
        headers=member_h,
    )
    assert reacted.status_code == 409

    # Reads stay open; the name is free for a fresh channel.
    page = await client.get(
        f"/chat/rooms/{cid}/messages", headers=member_h
    )
    assert page.status_code == 200
    inbox = await client.get("/chat/inbox", headers=member_h)
    assert all(
        row["room_id"] != cid for row in inbox.json()["items"]
    )
    reuse = await client.post(
        f"/orgs/{org_id}/chat/channels",
        json={"name": "legacy"},
        headers=owner_h,
    )
    assert reuse.status_code == 201, reuse.text
