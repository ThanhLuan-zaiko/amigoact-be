"""Regression: a trashed event no longer accepts chat in its thread.

Before the fix, soft-deleting an event left its linked sub-thread fully
writable and still labelled with the event title. This freezes the 410
ACTIVITY_DELETED envelope for a member posting there, and the refusal
of a new thread opened on the trashed event.
"""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_workspace_db import _org_with_member


async def test_trashed_event_thread_rejects_posts(
    client: AsyncClient,
) -> None:
    org_id, owner_h, member_h, _ = await _org_with_member(
        client, "evt-trash-freeze"
    )
    drafted = await client.post(
        f"/orgs/{org_id}/activities",
        json={
            "title": "Hien mau",
            "is_remote": False,
            "start_at": "2030-01-10T09:00:00Z",
            "hours_awarded": 0,
        },
        headers=owner_h,
    )
    activity_id = drafted.json()["id"]
    thread_body = {
        "name": "Su kien hien mau",
        "topic": "",
        "kind": "text",
        "post_policy": "everyone",
        "activity_id": activity_id,
    }
    opened = await client.post(
        f"/orgs/{org_id}/chat/rooms/{org_id}/threads",
        json=thread_body,
        headers=owner_h,
    )
    thread_id = opened.json()["channel_id"]
    await client.delete(
        f"/orgs/{org_id}/activities/{activity_id}", headers=owner_h
    )

    denied = await client.post(
        f"/chat/rooms/{thread_id}/messages",
        json={"body": "con ai khong"},
        headers=member_h,
    )
    assert denied.status_code == 410, denied.text
    assert denied.json() == {
        "code": "ACTIVITY_DELETED",
        "message": "The linked event is deleted.",
    }

    late = await client.post(
        f"/orgs/{org_id}/chat/rooms/{org_id}/threads",
        json={**thread_body, "name": "Luong muon"},
        headers=owner_h,
    )
    assert late.status_code == 410, late.text
    assert late.json()["code"] == "ACTIVITY_DELETED"
