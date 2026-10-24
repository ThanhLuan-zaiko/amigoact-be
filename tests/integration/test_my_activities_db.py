"""Integration tests: /me/activities across orgs, rights and the trash view."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_workspace_db import _org_with_member


async def test_feed_spans_orgs_and_marks_manage_rights(
    client: AsyncClient,
) -> None:
    org_id, owner_h, member_h, _ = await _org_with_member(client, "feed-a")
    second = await client.post(
        "/orgs",
        json={
            "name": "Feed B", "slug": "feed-b",
            "description": "D", "kind": "club",
        },
        headers=owner_h,
    )
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]
    created = await client.post(
        f"/orgs/{org_id}/activities",
        json={
            "title": "Feed Run", "location": "Park",
            "is_remote": False, "hours_awarded": 2,
            "start_at": "2030-06-02T08:00:00Z",
        },
        headers=owner_h,
    )
    assert created.status_code == 201, created.text

    owner_feed = (await client.get("/me/activities", headers=owner_h)).json()
    org_ids = {org["id"] for org in owner_feed["orgs"]}
    assert {org_id, second_id} <= org_ids
    row = next(r for r in owner_feed["items"] if r["title"] == "Feed Run")
    assert row["org_id"] == org_id
    assert row["can_manage"] is True

    member_feed = (
        await client.get("/me/activities", headers=member_h)
    ).json()
    assert [org["id"] for org in member_feed["orgs"]] == [org_id]
    assert member_feed["orgs"][0]["can_manage"] is False
    assert member_feed["orgs"][0]["can_create"] is False
    assert [r["title"] for r in member_feed["items"]] == ["Feed Run"]
    assert member_feed["items"][0]["can_manage"] is False


async def test_trash_view_is_manager_only(client: AsyncClient) -> None:
    org_id, owner_h, member_h, _ = await _org_with_member(client, "feed-trash")
    created = await client.post(
        f"/orgs/{org_id}/activities",
        json={
            "title": "Bin Run", "is_remote": False,
            "hours_awarded": 0, "start_at": "2030-06-03T08:00:00Z",
        },
        headers=owner_h,
    )
    activity_id = created.json()["id"]
    deleted = await client.delete(
        f"/orgs/{org_id}/activities/{activity_id}", headers=owner_h
    )
    assert deleted.status_code == 200, deleted.text

    live = (await client.get("/me/activities", headers=owner_h)).json()
    assert all(r["id"] != activity_id for r in live["items"])

    owner_trash = (
        await client.get("/me/activities?trash=1", headers=owner_h)
    ).json()
    assert [r["id"] for r in owner_trash["items"]] == [activity_id]
    assert owner_trash["items"][0]["deleted_at"] is not None

    member_trash = (
        await client.get("/me/activities?trash=1", headers=member_h)
    ).json()
    assert member_trash["items"] == []
    assert member_trash["orgs"] == []
