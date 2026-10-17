"""Integration tests: GET /chat/inbox over HTTP across orgs."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_workspace_db import (
    _headers,
    _org_with_member,
    _token,
)


async def test_chat_inbox_merges_room_kinds_across_orgs(
    client: AsyncClient,
) -> None:
    org_id, owner_h, member_h, member_id = await _org_with_member(
        client, "ws-inbox"
    )
    outsider = await _token(client, "ws-inbox-out@x.com", "0912347008")
    outsider_h = _headers(outsider)

    # One activity room joins the general room in the same org.
    created = await client.post(
        f"/orgs/{org_id}/activities",
        json={
            "title": "Inbox Activity",
            "description": "d",
            "location": "X",
            "city": "X",
            "is_remote": False,
            "start_at": "2030-06-01T08:00:00Z",
            "end_at": "2030-06-01T12:00:00Z",
            "hours_awarded": 2.0,
        },
        headers=owner_h,
    )
    assert created.status_code == 201, created.text
    activity_id = created.json()["id"]

    # A dm room between owner and member.
    opened = await client.post(
        f"/orgs/{org_id}/chat/dm",
        json={"peer_id": member_id},
        headers=owner_h,
    )
    assert opened.status_code == 201, opened.text
    dm_room = opened.json()["room_id"]

    # Newest messages: general gets one from the member so the owner
    # sees a live preview plus an unread badge.
    sent = await client.post(
        f"/orgs/{org_id}/chat/messages",
        json={"body": "hello inbox"},
        headers=member_h,
    )
    assert sent.status_code == 201

    inbox = await client.get("/chat/inbox", headers=owner_h)
    assert inbox.status_code == 200, inbox.text
    rows = {row["room_id"]: row for row in inbox.json()["items"]}
    assert rows[org_id]["kind"] == "general"
    assert rows[org_id]["last_body"] == "hello inbox"
    assert rows[org_id]["unread"] == 1
    assert rows[org_id]["last_author_name"] == "Ws User"
    assert rows[activity_id]["kind"] == "activity"
    assert rows[activity_id]["title"] == "Inbox Activity"
    assert rows[activity_id]["unread"] == 0
    assert rows[dm_room]["kind"] == "dm"
    assert rows[dm_room]["peer_id"] == member_id
    # The freshest room floats to the top.
    assert inbox.json()["items"][0]["room_id"] == org_id

    # The sender's own inbox never counts their own message as unread.
    member_inbox = await client.get("/chat/inbox", headers=member_h)
    member_rows = {
        row["room_id"]: row for row in member_inbox.json()["items"]
    }
    assert member_rows[org_id]["unread"] == 0
    assert member_rows[dm_room]["peer_id"] != member_id

    # An outsider has no rooms of this org anywhere in their inbox.
    blocked = await client.get("/chat/inbox", headers=outsider_h)
    assert blocked.status_code == 200
    assert all(
        row["org_id"] != org_id for row in blocked.json()["items"]
    )

    # Auth is mandatory on the merged inbox too.
    anon = await client.get("/chat/inbox")
    assert anon.status_code == 401
