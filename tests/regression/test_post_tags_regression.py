"""Regression: post tag chips, the 3-tag cap, and reserved slugs."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_workspace_db import _org_with_member


async def test_post_tag_contract(client: AsyncClient) -> None:
    """Chips are {name, slug}; four names are 422; a dead slug is 410."""
    org_id, owner_h, member_h, _ = await _org_with_member(client, "rg-ptag", writer=True)
    base = f"/orgs/{org_id}/posts"
    made = await client.post(
        base,
        json={"kind": "discussion", "body": "x", "tags": ["Alpha"]},
        headers=member_h,
    )
    assert made.status_code == 201, made.text
    assert set(made.json()["tags"][0].keys()) == {"name", "slug"}
    assert made.json()["tags"] == [{"name": "Alpha", "slug": "alpha"}]

    renamed = await client.patch(
        f"/orgs/{org_id}/tags/alpha",
        json={"name": "ALPHA"},
        headers=owner_h,
    )
    assert renamed.status_code == 200, renamed.text
    detail = await client.get(
        f"{base}/{made.json()['post_id']}", headers=member_h
    )
    assert detail.json()["tags"] == [{"name": "ALPHA", "slug": "alpha"}]

    too_many = await client.post(
        base,
        json={
            "kind": "discussion",
            "body": "x",
            "tags": ["A", "B", "C", "D"],
        },
        headers=member_h,
    )
    assert too_many.status_code == 422

    trashed = await client.delete(
        f"/orgs/{org_id}/tags/alpha", headers=owner_h
    )
    assert trashed.status_code == 200, trashed.text
    blocked = await client.post(
        base,
        json={"kind": "discussion", "body": "x", "tags": ["Alpha"]},
        headers=member_h,
    )
    assert blocked.status_code == 410
    assert set(blocked.json().keys()) == {"code", "message"}
    assert blocked.json()["code"] == "TAG_DELETED"
