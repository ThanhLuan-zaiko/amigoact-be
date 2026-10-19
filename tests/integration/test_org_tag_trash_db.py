"""Integration: org tag soft delete, restore and hard delete over HTTP."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_org_tags_db import (
    _activity,
    _get_activity,
)
from tests.integration.test_activity_tags_db import (
    _headers,
    _org,
    _publish,
)
from tests.integration.test_workspace_db import (
    _headers as _wrap_headers,
    _org_with_member,
    _token,
)


async def test_trash_restore_round_trip(client: AsyncClient) -> None:
    owner = await _headers(client, "tt.own@example.com", "0903000070")
    org_id = await _org(client, owner, "tt-round")
    activity = await _activity(client, org_id, owner, ["Alpha", "Beta"])
    aid = activity["id"]
    await _publish(client, org_id, aid, owner)

    trashed = await client.delete(
        f"/orgs/{org_id}/tags/alpha", headers=owner
    )
    assert trashed.status_code == 200, trashed.text
    assert trashed.json()["deleted_at"] is not None

    detail = await _get_activity(client, aid, owner)
    assert detail["tags"] == [{"name": "Beta", "slug": "beta"}]
    feed = await client.get("/activities?tag=alpha")
    assert all(r["id"] != aid for r in feed.json())
    public = await client.get("/tags?q=alpha")
    assert all(r["slug"] != "alpha" for r in public.json())

    live = await client.get(f"/orgs/{org_id}/tags", headers=owner)
    assert [i["slug"] for i in live.json()["items"]] == ["beta"]
    assert live.json()["trash_count"] == 1

    trash = await client.get(
        f"/orgs/{org_id}/tags?trash=1", headers=owner
    )
    assert trash.status_code == 200
    rows = {i["slug"]: i for i in trash.json()["items"]}
    assert rows["alpha"]["activity_count"] == 1
    assert rows["alpha"]["deleted_at"] is not None

    restored = await client.post(
        f"/orgs/{org_id}/tags/alpha/restore", headers=owner
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["deleted_at"] is None

    detail = await _get_activity(client, aid, owner)
    assert detail["tags"] == [
        {"name": "Beta", "slug": "beta"},
        {"name": "Alpha", "slug": "alpha"},
    ]
    feed = await client.get("/activities?tag=alpha")
    assert any(r["id"] == aid for r in feed.json())


async def test_trashed_slug_blocks_reuse(client: AsyncClient) -> None:
    owner = await _headers(client, "tt.blk@example.com", "0903000071")
    org_id = await _org(client, owner, "tt-block")
    await client.post(
        f"/orgs/{org_id}/tags", json={"name": "Alpha"}, headers=owner
    )
    await client.delete(f"/orgs/{org_id}/tags/alpha", headers=owner)

    activity = await client.post(
        f"/orgs/{org_id}/activities",
        json={
            "title": "Blocked", "location": "Park",
            "is_remote": False, "hours_awarded": 1.0,
            "start_at": "2030-06-03T08:00:00Z",
            "tags": ["alpha"],
        },
        headers=owner,
    )
    assert activity.status_code == 410
    assert activity.json()["code"] == "TAG_DELETED"

    created = await client.post(
        f"/orgs/{org_id}/tags", json={"name": "Alpha"}, headers=owner
    )
    assert created.status_code == 410
    assert created.json()["code"] == "TAG_DELETED"


async def test_hard_delete_trashed_then_recreate(
    client: AsyncClient,
) -> None:
    owner = await _headers(client, "tt.hard@example.com", "0903000072")
    org_id = await _org(client, owner, "tt-hard")
    await client.post(
        f"/orgs/{org_id}/tags", json={"name": "Alpha"}, headers=owner
    )
    await client.delete(f"/orgs/{org_id}/tags/alpha", headers=owner)

    erased = await client.delete(
        f"/orgs/{org_id}/tags/alpha?hard=1", headers=owner
    )
    assert erased.status_code == 204
    assert not erased.content

    restore = await client.post(
        f"/orgs/{org_id}/tags/alpha/restore", headers=owner
    )
    assert restore.status_code == 404
    assert restore.json()["code"] == "TAG_NOT_FOUND"

    created = await client.post(
        f"/orgs/{org_id}/tags", json={"name": "Alpha"}, headers=owner
    )
    assert created.status_code == 201


async def test_hard_delete_live_tag_strips_activities(
    client: AsyncClient,
) -> None:
    owner = await _headers(client, "tt.hl@example.com", "0903000073")
    org_id = await _org(client, owner, "tt-hardlive")
    activity = await _activity(client, org_id, owner, ["Alpha", "Beta"])
    erased = await client.delete(
        f"/orgs/{org_id}/tags/alpha?hard=1", headers=owner
    )
    assert erased.status_code == 204
    detail = await _get_activity(client, activity["id"], owner)
    assert detail["tags"] == [{"name": "Beta", "slug": "beta"}]


async def test_member_denied_every_trash_mutation(
    client: AsyncClient,
) -> None:
    org_id, owner_h, member_h, _ = await _org_with_member(
        client, "tt-perms"
    )
    await _activity(client, org_id, owner_h, ["Alpha"])

    trashed = await client.get(
        f"/orgs/{org_id}/tags?trash=1", headers=member_h
    )
    assert trashed.status_code == 403
    for method, path in (
        ("delete", f"/orgs/{org_id}/tags/alpha"),
        ("delete", f"/orgs/{org_id}/tags/alpha?hard=1"),
        ("post", f"/orgs/{org_id}/tags/alpha/restore"),
    ):
        res = await client.request(method, path, headers=member_h)
        assert res.status_code == 403, (method, path, res.text)


async def test_purged_activity_drops_remembered_edges(
    client: AsyncClient,
) -> None:
    owner = await _headers(client, "tt.purge@example.com", "0903000074")
    org_id = await _org(client, owner, "tt-purge")
    activity = await _activity(client, org_id, owner, ["Solo"])
    await client.delete(f"/orgs/{org_id}/tags/solo", headers=owner)

    # Hard-delete the only remembered activity: the purge clears its
    # remembered edge rows too, so the trash count drops to zero.
    purged = await client.delete(
        f"/orgs/{org_id}/activities/{activity['id']}?hard=1",
        headers=owner,
    )
    assert purged.status_code in (200, 204), purged.text

    trash = await client.get(
        f"/orgs/{org_id}/tags?trash=1", headers=owner
    )
    assert trash.json()["items"][0]["activity_count"] == 0

    restored = await client.post(
        f"/orgs/{org_id}/tags/solo/restore", headers=owner
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["activity_count"] == 0
