"""Integration: saving an activity claims the author's personal tag."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_activity_tags_db import _BODY, _headers, _org


async def test_activity_save_lists_the_tag_on_the_author(client: AsyncClient) -> None:
    owner = await _headers(client, "act.tag@example.com", "0903000091")
    org_id = await _org(client, owner, "act-tag-club")
    created = await client.post(
        f"/orgs/{org_id}/activities",
        json={**_BODY, "title": "Don dep bien", "tags": ["Mua he"]},
        headers=owner,
    )
    assert created.status_code == 201, created.text
    activity_id = created.json()["id"]

    listed = await client.get("/me/tags", headers=owner)
    assert listed.status_code == 200, listed.text
    tag = next(item for item in listed.json() if item["slug"] == "mua-he")
    assert tag["post_count"] == 0
    assert tag["activity_count"] == 1
    assert tag["activities"] == [
        {
            "activity_id": activity_id,
            "org_id": org_id,
            "title": "Don dep bien",
            "draft": True,
        }
    ]


async def test_org_rename_moves_the_personal_rail(client: AsyncClient) -> None:
    owner = await _headers(client, "act.move@example.com", "0903000093")
    org_id = await _org(client, owner, "act-move-club")
    created = await client.post(
        f"/orgs/{org_id}/activities",
        json={**_BODY, "title": "Don dep bien", "tags": ["Mua he"]},
        headers=owner,
    )
    assert created.status_code == 201, created.text
    activity_id = created.json()["id"]
    renamed = await client.patch(
        f"/orgs/{org_id}/tags/mua-he",
        json={"name": "Mua dong"},
        headers=owner,
    )
    assert renamed.status_code == 200, renamed.text
    listed = await client.get("/me/tags", headers=owner)
    tags = {item["slug"]: item for item in listed.json()}
    assert tags["mua-dong"]["activity_count"] == 1
    assert tags["mua-dong"]["activities"][0]["activity_id"] == activity_id
    assert tags["mua-he"]["activity_count"] == 0


async def test_purge_clears_the_personal_rail(client: AsyncClient) -> None:
    owner = await _headers(client, "act.purge@example.com", "0903000094")
    org_id = await _org(client, owner, "act-purge-club")
    created = await client.post(
        f"/orgs/{org_id}/activities",
        json={**_BODY, "tags": ["Mua he"]},
        headers=owner,
    )
    activity_id = created.json()["id"]
    purged = await client.delete(
        f"/orgs/{org_id}/activities/{activity_id}?hard=true",
        headers=owner,
    )
    assert purged.status_code == 204, purged.text
    listed = await client.get("/me/tags", headers=owner)
    tag = next(item for item in listed.json() if item["slug"] == "mua-he")
    assert tag["activity_count"] == 0
    assert tag["activities"] == []


async def test_restore_lists_a_soft_deleted_activity(client: AsyncClient) -> None:
    owner = await _headers(client, "act.restore@example.com", "0903000100")
    org_id = await _org(client, owner, "act-restore-club")
    created = await client.post(
        f"/orgs/{org_id}/activities",
        json={**_BODY, "tags": ["Mua he"]},
        headers=owner,
    )
    activity_id = created.json()["id"]
    trashed = await client.delete(
        f"/orgs/{org_id}/activities/{activity_id}", headers=owner
    )
    assert trashed.status_code == 200, trashed.text
    hidden = await client.get("/me/tags", headers=owner)
    hidden_tag = next(item for item in hidden.json() if item["slug"] == "mua-he")
    assert hidden_tag["activity_count"] == 0
    restored = await client.post(
        f"/orgs/{org_id}/activities/{activity_id}/restore", headers=owner
    )
    assert restored.status_code == 200, restored.text
    listed = await client.get("/me/tags", headers=owner)
    tag = next(item for item in listed.json() if item["slug"] == "mua-he")
    assert tag["activity_count"] == 1
    assert tag["activities"][0]["activity_id"] == activity_id


async def test_personal_rename_refuses_a_trashed_org_slug(
    client: AsyncClient,
) -> None:
    owner = await _headers(client, "act.trash@example.com", "0903000095")
    org_id = await _org(client, owner, "act-trash-club")
    created = await client.post(
        f"/orgs/{org_id}/activities",
        json={**_BODY, "tags": ["Mua he"]},
        headers=owner,
    )
    activity_id = created.json()["id"]
    catalog = await client.post(
        f"/orgs/{org_id}/tags",
        json={"name": "Bi cam"},
        headers=owner,
    )
    assert catalog.status_code == 201, catalog.text
    trashed = await client.delete(
        f"/orgs/{org_id}/tags/bi-cam", headers=owner
    )
    assert trashed.status_code == 200, trashed.text
    renamed = await client.patch(
        "/me/tags/mua-he", json={"name": "Bi cam"}, headers=owner
    )
    assert renamed.status_code == 410, renamed.text
    assert renamed.json()["code"] == "TAG_DELETED"
    detail = await client.get(f"/activities/{activity_id}", headers=owner)
    assert detail.json()["tags"] == [{"name": "Mua he", "slug": "mua-he"}]
