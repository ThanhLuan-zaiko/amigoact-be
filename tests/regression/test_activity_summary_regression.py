"""Regression: org list rows carry location, remote flag and hours.

The /manage/events cards read these fields from the summary. Before this
change only the detail endpoint returned them, so the list could not show
where or how many hours an activity carries. Locks the summary keys too.
"""

from __future__ import annotations

from httpx import AsyncClient

from tests.regression.test_activities_regression import _headers

SUMMARY_KEYS = {
    "id", "org_id", "title", "slug", "status", "start_at", "category_id",
    "tags", "deleted_at", "location", "is_remote", "hours_awarded",
}


async def test_org_list_summary_carries_location_remote_and_hours(
    client: AsyncClient,
) -> None:
    headers = await _headers(client, "r.sum@example.com", "0903000030")
    org = await client.post(
        "/orgs",
        json={
            "name": "Sum Club", "slug": "sum-club",
            "description": "", "kind": "club",
        },
        headers=headers,
    )
    org_id = org.json()["id"]
    created = await client.post(
        f"/orgs/{org_id}/activities",
        json={
            "title": "Sum Run", "location": "Park",
            "is_remote": False, "hours_awarded": 2.5,
            "start_at": "2030-06-02T08:00:00Z",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text

    listed = await client.get(f"/orgs/{org_id}/activities", headers=headers)
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert len(rows) == 1
    assert set(rows[0].keys()) == SUMMARY_KEYS
    assert rows[0]["location"] == "Park"
    assert rows[0]["is_remote"] is False
    assert rows[0]["hours_awarded"] == 2.5
