"""Regression: owned-tag suggestions are a copy list, not a shared row."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_activity_tags_db import _headers, _org


async def test_owned_tag_item_keys(client: AsyncClient) -> None:
    owner = await _headers(client, "rg.own@example.com", "0903000085")
    source = await _org(client, owner, "rg-own-a")
    current = await _org(client, owner, "rg-own-b")
    await client.post(
        f"/orgs/{source}/tags", json={"name": "Alpha"}, headers=owner
    )
    listed = await client.get(
        f"/orgs/{current}/tags/owned", headers=owner
    )
    assert listed.status_code == 200, listed.text
    assert set(listed.json()[0].keys()) == {
        "name", "slug", "org_id", "org_name",
    }
