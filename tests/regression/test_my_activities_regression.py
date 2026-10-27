"""Regression: freeze the /me/activities response shape and trash gate.

Locks the item keys (the summary plus can_manage), the org keys the rail
reads, and the rule that trashed rows never reach a caller who cannot
manage the org. The manage page depends on all three.
"""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_workspace_db import _org_with_member

ITEM_KEYS = {
    "id", "org_id", "title", "slug", "status", "start_at", "category_id",
    "tags", "deleted_at", "location", "is_remote", "hours_awarded",
    "can_manage", "can_delete",
}
ORG_KEYS = {
    "id", "name", "slug", "kind", "can_create", "can_manage", "can_delete",
    "activity_count", "logo_url",
}


async def test_my_activities_shape_and_trash_gate(
    client: AsyncClient,
) -> None:
    org_id, owner_h, member_h, _ = await _org_with_member(client, "reg-mine")
    created = await client.post(
        f"/orgs/{org_id}/activities",
        json={
            "title": "Reg Mine", "location": "Park",
            "is_remote": False, "hours_awarded": 1,
            "start_at": "2030-07-01T08:00:00Z",
        },
        headers=owner_h,
    )
    assert created.status_code == 201, created.text

    feed = (await client.get("/me/activities", headers=owner_h)).json()
    assert set(feed.keys()) == {"items", "orgs"}
    assert feed["items"] and set(feed["items"][0].keys()) == ITEM_KEYS
    assert feed["orgs"] and set(feed["orgs"][0].keys()) == ORG_KEYS

    member_feed = (
        await client.get("/me/activities", headers=member_h)
    ).json()
    assert member_feed["items"] and all(
        item["can_manage"] is False for item in member_feed["items"]
    )

    trash = await client.get("/me/activities?trash=1", headers=member_h)
    assert trash.status_code == 200, trash.text
    assert trash.json() == {"items": [], "orgs": []}
