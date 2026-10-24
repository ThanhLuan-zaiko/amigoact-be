"""Regression: an event thread needs the owner or activity:create.

Before the fix, any active org member could POST a sub-thread carrying an
activity_id, because only the draft endpoint checked activity:create. This
freezes the 403 FORBIDDEN envelope for a plain member and the 201 path for
the owner who opens the same event thread.
"""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_workspace_db import _org_with_member


async def test_plain_member_cannot_open_event_thread(
    client: AsyncClient,
) -> None:
    org_id, owner_h, member_h, _ = await _org_with_member(
        client, "evt-thread-gate"
    )
    drafted = await client.post(
        f"/orgs/{org_id}/activities",
        json={
            "title": "Don mau tinh nguyen",
            "is_remote": False,
            "start_at": "2030-01-10T09:00:00Z",
            "hours_awarded": 0,
        },
        headers=owner_h,
    )
    assert drafted.status_code == 201, drafted.text
    activity_id = drafted.json()["id"]

    thread_body = {
        "name": "Su kien don mau",
        "topic": "",
        "kind": "text",
        "post_policy": "everyone",
        "activity_id": activity_id,
    }
    denied = await client.post(
        f"/orgs/{org_id}/chat/rooms/{org_id}/threads",
        json=thread_body,
        headers=member_h,
    )
    assert denied.status_code == 403, denied.text
    assert denied.json()["code"] == "FORBIDDEN"

    opened = await client.post(
        f"/orgs/{org_id}/chat/rooms/{org_id}/threads",
        json={**thread_body, "name": "Su kien cua chu"},
        headers=owner_h,
    )
    assert opened.status_code == 201, opened.text
    assert opened.json()["activity_id"] == activity_id
