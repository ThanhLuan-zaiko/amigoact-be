"""Integration: event trash freezes its chat, hard delete purges it."""

from __future__ import annotations

from datetime import datetime, timezone

from httpx import AsyncClient

from chat.helpers import bucket_of
from chat.model import OrgRoomMessage
from tests.integration.test_workspace_db import _org_with_member


async def _event(client: AsyncClient, org_id: str, owner: dict) -> str:
    drafted = await client.post(
        f"/orgs/{org_id}/activities",
        json={
            "title": "Trong cay ven song",
            "is_remote": False,
            "start_at": "2030-03-01T08:00:00Z",
            "hours_awarded": 0,
        },
        headers=owner,
    )
    assert drafted.status_code == 201, drafted.text
    return drafted.json()["id"]


async def _send(client: AsyncClient, room_id: str, headers: dict, body: str):  # noqa: ANN202
    return await client.post(
        f"/chat/rooms/{room_id}/messages",
        json={"body": body},
        headers=headers,
    )


async def test_trash_freezes_and_restore_reopens_event_chat(
    client: AsyncClient,
) -> None:
    org_id, owner, member, _ = await _org_with_member(client, "evt-chat-trash")
    aid = await _event(client, org_id, owner)
    opened = await client.post(
        f"/orgs/{org_id}/chat/rooms/{org_id}/threads",
        json={
            "name": "Ban to chuc", "topic": "", "kind": "text",
            "post_policy": "everyone", "activity_id": aid,
        },
        headers=owner,
    )
    assert opened.status_code == 201, opened.text
    thread_id = opened.json()["channel_id"]
    assert (await _send(client, thread_id, member, "truoc")).status_code == 201

    trashed = await client.delete(
        f"/orgs/{org_id}/activities/{aid}", headers=owner
    )
    assert trashed.status_code == 200, trashed.text
    for room_id in (thread_id, aid):
        frozen = await _send(client, room_id, member, "sau")
        assert frozen.status_code == 410, frozen.text
        assert frozen.json()["code"] == "ACTIVITY_DELETED"
    history = await client.get(
        f"/chat/rooms/{thread_id}/messages", headers=member
    )
    assert history.status_code == 200, history.text
    listed = await client.get(
        f"/orgs/{org_id}/chat/rooms/{org_id}/threads", headers=owner
    )
    assert listed.json()["items"][0]["activity_deleted"] is True
    inbox = await client.get("/chat/inbox", headers=member)
    rows = {row["room_id"]: row for row in inbox.json()["items"]}
    assert aid not in rows
    assert rows[thread_id]["activity_deleted"] is True

    restored = await client.post(
        f"/orgs/{org_id}/activities/{aid}/restore", headers=owner
    )
    assert restored.status_code == 200, restored.text
    assert (await _send(client, thread_id, member, "lai")).status_code == 201


async def test_hard_delete_purges_room_and_archives_thread(
    client: AsyncClient,
) -> None:
    org_id, owner, member, _ = await _org_with_member(client, "evt-chat-purge")
    aid = await _event(client, org_id, owner)
    opened = await client.post(
        f"/orgs/{org_id}/chat/rooms/{org_id}/threads",
        json={
            "name": "Hau can", "topic": "", "kind": "text",
            "post_policy": "everyone", "activity_id": aid,
        },
        headers=owner,
    )
    thread_id = opened.json()["channel_id"]
    assert (await _send(client, aid, member, "phong su kien")).status_code == 201
    assert (await _send(client, thread_id, member, "luong")).status_code == 201

    purged = await client.delete(
        f"/orgs/{org_id}/activities/{aid}?hard=true", headers=owner
    )
    assert purged.status_code == 204, purged.text

    bucket = bucket_of(datetime.now(timezone.utc))
    assert OrgRoomMessage.objects(room_id=aid, bucket=bucket).count() == 0
    gone = await client.get(f"/chat/rooms/{aid}/messages", headers=member)
    assert gone.status_code == 404, gone.text
    # The linked thread is archived with its history kept for managers.
    listed = await client.get(
        f"/orgs/{org_id}/chat/rooms/{org_id}/threads", headers=owner
    )
    row = next(
        t for t in listed.json()["items"] if t["channel_id"] == thread_id
    )
    assert row["archived_at"] is not None
    assert row["activity_deleted"] is True
    assert row["activity_title"] is None
    kept = await client.get(
        f"/chat/rooms/{thread_id}/messages", headers=owner
    )
    assert kept.status_code == 200 and kept.json()["items"], kept.text
    blocked = await _send(client, thread_id, owner, "nua")
    assert blocked.status_code in (409, 410), blocked.text
