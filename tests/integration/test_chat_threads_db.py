"""Integration tests: room sub-thread endpoints + inherited gates."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_workspace_db import (
    _headers,
    _org_with_member,
    _token,
)


async def _invite_member(
    client: AsyncClient,
    org_id: str,
    owner_h: dict,
    email: str,
    phone: str,
) -> dict:
    """Second seat via the same invite+accept flow as _org_with_member."""
    token = await _token(client, email, phone)
    member_h = _headers(token)
    invited = await client.post(
        f"/orgs/{org_id}/members",
        json={"email": email},
        headers=owner_h,
    )
    assert invited.status_code == 201, invited.text
    accepted = await client.post(
        f"/orgs/{org_id}/members/me/accept", headers=member_h
    )
    assert accepted.status_code == 200, accepted.text
    return member_h


async def test_room_thread_flow(client: AsyncClient) -> None:
    org_id, owner_h, member_h, _ = await _org_with_member(
        client, "thr-basic"
    )

    # Any org member opens a thread inside the general room.
    created = await client.post(
        f"/orgs/{org_id}/chat/rooms/{org_id}/threads",
        json={
            "name": "Chien dich mua he",
            "topic": "Planning",
            "kind": "task",
        },
        headers=member_h,
    )
    assert created.status_code == 201, created.text
    thread = created.json()
    tid = thread["channel_id"]
    assert thread["parent_room_id"] == org_id
    assert thread["kind"] == "task"
    assert thread["visibility"] == "org"

    # The per-room listing returns it for both members.
    listed = await client.get(
        f"/orgs/{org_id}/chat/rooms/{org_id}/threads",
        headers=owner_h,
    )
    assert [row["channel_id"] for row in listed.json()["items"]] == [
        tid
    ]

    # The thread is a full room: post + read + inbox row all work.
    sent = await client.post(
        f"/chat/rooms/{tid}/messages",
        json={"body": "bat dau nao"},
        headers=member_h,
    )
    assert sent.status_code == 201, sent.text
    inbox = await client.get("/chat/inbox", headers=owner_h)
    row = next(
        item for item in inbox.json()["items"] if item["room_id"] == tid
    )
    assert row["kind"] == "channel"
    assert row["parent_room_id"] == org_id
    assert row["last_body"] == "bat dau nao"

    # The org channel directory stays flat: threads never leak in.
    directory = await client.get(
        f"/orgs/{org_id}/chat/channels", headers=owner_h
    )
    assert all(
        item["channel_id"] != tid for item in directory.json()["items"]
    )


async def test_thread_names_and_nesting(client: AsyncClient) -> None:
    org_id, owner_h, member_h, _ = await _org_with_member(
        client, "thr-name"
    )
    parent = await client.post(
        f"/orgs/{org_id}/chat/channels",
        json={"name": "ops"},
        headers=owner_h,
    )
    pid = parent.json()["channel_id"]

    first = await client.post(
        f"/orgs/{org_id}/chat/rooms/{org_id}/threads",
        json={"name": "trung-ten"},
        headers=member_h,
    )
    assert first.status_code == 201, first.text
    # Same folded name in another parent room is a different scope.
    second = await client.post(
        f"/orgs/{org_id}/chat/rooms/{pid}/threads",
        json={"name": "TRUNG-TEN"},
        headers=member_h,
    )
    assert second.status_code == 201, second.text
    dup = await client.post(
        f"/orgs/{org_id}/chat/rooms/{org_id}/threads",
        json={"name": "Trung-Ten"},
        headers=member_h,
    )
    assert (dup.status_code, dup.json()["code"]) == (
        409,
        "CHANNEL_NAME_TAKEN",
    )

    # Threads never nest.
    nested = await client.post(
        f"/orgs/{org_id}/chat/rooms/{first.json()['channel_id']}/threads",
        json={"name": "sub-sub"},
        headers=member_h,
    )
    assert (nested.status_code, nested.json()["code"]) == (
        400,
        "INVALID_CHANNEL_STATE",
    )


async def test_restricted_parent_thread_gate(client: AsyncClient) -> None:
    org_id, owner_h, member_h, member_id = await _org_with_member(
        client, "thr-gate"
    )
    parent = await client.post(
        f"/orgs/{org_id}/chat/channels",
        json={"name": "core", "visibility": "restricted"},
        headers=owner_h,
    )
    pid = parent.json()["channel_id"]

    # Unseated member cannot create or list threads there.
    denied = await client.post(
        f"/orgs/{org_id}/chat/rooms/{pid}/threads",
        json={"name": "inside"},
        headers=member_h,
    )
    assert denied.status_code == 403
    denied = await client.get(
        f"/orgs/{org_id}/chat/rooms/{pid}/threads", headers=member_h
    )
    assert denied.status_code == 403

    await client.post(
        f"/orgs/{org_id}/chat/channels/{pid}/members",
        json={"user_id": member_id},
        headers=owner_h,
    )
    created = await client.post(
        f"/orgs/{org_id}/chat/rooms/{pid}/threads",
        json={"name": "inside"},
        headers=member_h,
    )
    assert created.status_code == 201, created.text
    tid = created.json()["channel_id"]
    assert created.json()["visibility"] == "restricted"

    # Seated members read the thread room; unseated org members cannot.
    page = await client.get(
        f"/chat/rooms/{tid}/messages", headers=member_h
    )
    assert page.status_code == 200, page.text
    other_h = await _invite_member(
        client, org_id, owner_h, "thr-gate-o2@x.com", "0912347099"
    )
    blocked = await client.get(
        f"/chat/rooms/{tid}/messages", headers=other_h
    )
    assert blocked.status_code == 403
    hidden = await client.get("/chat/inbox", headers=other_h)
    assert all(
        row["room_id"] != tid for row in hidden.json()["items"]
    )
