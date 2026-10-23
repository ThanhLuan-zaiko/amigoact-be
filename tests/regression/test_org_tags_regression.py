"""Regression: freeze the org tag API contracts and error envelopes."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_activity_tags_db import (
    _BODY,
    _headers,
    _org,
)


async def test_org_tag_page_and_item_shape(client: AsyncClient) -> None:
    """Contract: OrgTagPage {items,can_manage}; item keys stay exact."""
    owner = await _headers(client, "rt.own@example.com", "0903000050")
    org_id = await _org(client, owner, "rt-shape")
    await client.post(
        f"/orgs/{org_id}/activities",
        json={**_BODY, "tags": ["Alpha"]},
        headers=owner,
    )
    res = await client.get(f"/orgs/{org_id}/tags", headers=owner)
    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) == {"items", "can_manage", "trash_count"}
    item = next(i for i in body["items"] if i["slug"] == "alpha")
    assert set(item.keys()) == {
        "id", "name", "slug", "activity_count", "post_count",
        "created_at", "deleted_at",
    }


async def test_tag_error_envelopes(client: AsyncClient) -> None:
    """Contract: TAG_EXISTS/409, TAG_NOT_FOUND/404, INVALID_TAG_MERGE/400."""
    owner = await _headers(client, "rt.err@example.com", "0903000051")
    org_id = await _org(client, owner, "rt-errors")
    await client.post(
        f"/orgs/{org_id}/tags", json={"name": "Alpha"}, headers=owner
    )

    dup = await client.post(
        f"/orgs/{org_id}/tags", json={"name": "alpha"}, headers=owner
    )
    assert (dup.status_code, dup.json()["code"]) == (409, "TAG_EXISTS")

    missing = await client.delete(
        f"/orgs/{org_id}/tags/ghost?hard=1", headers=owner
    )
    assert (missing.status_code, missing.json()["code"]) == (
        404,
        "TAG_NOT_FOUND",
    )

    self_merge = await client.post(
        f"/orgs/{org_id}/tags/alpha/merge",
        json={"into": "alpha"},
        headers=owner,
    )
    assert (self_merge.status_code, self_merge.json()["code"]) == (
        400,
        "INVALID_TAG_MERGE",
    )


async def test_tag_manage_is_assignable(client: AsyncClient) -> None:
    """Contract: tag:manage shows up in assignable_permissions."""
    owner = await _headers(client, "rt.rbac@example.com", "0903000052")
    org_id = await _org(client, owner, "rt-rbac")
    roles = await client.get(f"/orgs/{org_id}/roles", headers=owner)
    assert roles.status_code == 200
    assert "tag:manage" in roles.json()["assignable_permissions"]


async def test_same_slug_keeps_each_orgs_spelling(
    client: AsyncClient,
) -> None:
    """Contract: shared-name behavior is intentionally gone; each org's
    catalog row owns its display name for the same slug."""
    owner_a = await _headers(client, "rt.a@example.com", "0903000053")
    owner_b = await _headers(client, "rt.b@example.com", "0903000054")
    org_a = await _org(client, owner_a, "rt-spell-a")
    org_b = await _org(client, owner_b, "rt-spell-b")
    first = await client.post(
        f"/orgs/{org_a}/activities",
        json={**_BODY, "tags": ["Tr\u1ed3ng r\u1eebng"]},
        headers=owner_a,
    )
    second = await client.post(
        f"/orgs/{org_b}/activities",
        json={**_BODY, "title": "Other", "tags": ["tr\u1ed3ng R\u1eeaNG"]},
        headers=owner_b,
    )
    assert first.json()["tags"][0]["name"] == "Tr\u1ed3ng r\u1eebng"
    assert second.json()["tags"][0]["name"] == "tr\u1ed3ng R\u1eeaNG"

    listed_a = await client.get(f"/orgs/{org_a}/tags", headers=owner_a)
    listed_b = await client.get(f"/orgs/{org_b}/tags", headers=owner_b)
    name_a = {
        i["slug"]: i["name"] for i in listed_a.json()["items"]
    }["trong-rung"]
    name_b = {
        i["slug"]: i["name"] for i in listed_b.json()["items"]
    }["trong-rung"]
    assert name_a == "Tr\u1ed3ng r\u1eebng"
    assert name_b == "tr\u1ed3ng R\u1eeaNG"


async def test_tag_trash_contract(client: AsyncClient) -> None:
    """Contract: soft delete 200+deleted_at, hard 204 empty, restore a
    live tag is INVALID_ORG_STATE, and a trashed slug blocks (410)."""
    owner = await _headers(client, "rt.trash@example.com", "0903000060")
    org_id = await _org(client, owner, "rt-trash")
    await client.post(
        f"/orgs/{org_id}/tags", json={"name": "Alpha"}, headers=owner
    )
    soft = await client.delete(
        f"/orgs/{org_id}/tags/alpha", headers=owner
    )
    assert soft.status_code == 200
    assert soft.json()["deleted_at"] is not None

    blocked = await client.post(
        f"/orgs/{org_id}/tags", json={"name": "Alpha"}, headers=owner
    )
    assert (blocked.status_code, blocked.json()["code"]) == (
        410,
        "TAG_DELETED",
    )

    restored = await client.post(
        f"/orgs/{org_id}/tags/alpha/restore", headers=owner
    )
    assert restored.status_code == 200
    again = await client.post(
        f"/orgs/{org_id}/tags/alpha/restore", headers=owner
    )
    assert (again.status_code, again.json()["code"]) == (
        400,
        "INVALID_ORG_STATE",
    )

    hard = await client.delete(
        f"/orgs/{org_id}/tags/alpha?hard=1", headers=owner
    )
    assert hard.status_code == 204
    assert not hard.content
