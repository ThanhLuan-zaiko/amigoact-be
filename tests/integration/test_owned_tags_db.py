"""Integration: an owner can copy a tag into another org they own."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_activity_tags_db import _BODY, _headers, _org


async def test_owned_tag_is_copied_and_then_independent(
    client: AsyncClient,
) -> None:
    """Choosing the suggestion claims a new row; a later rename stays put."""
    owner = await _headers(client, "own.tag@example.com", "0903000081")
    source = await _org(client, owner, "own-src")
    current = await _org(client, owner, "own-dst")
    made = await client.post(
        f"/orgs/{source}/tags",
        json={"name": "Hoc bong"},
        headers=owner,
    )
    assert made.status_code == 201, made.text

    suggestions = await client.get(
        f"/orgs/{current}/tags/owned", headers=owner
    )
    assert suggestions.status_code == 200, suggestions.text
    assert suggestions.json() == [
        {
            "name": "Hoc bong",
            "slug": "hoc-bong",
            "org_id": source,
            "org_name": "Club own-src",
        }
    ]
    before = await client.get(f"/orgs/{current}/tags", headers=owner)
    assert before.json()["items"] == []

    activity = await client.post(
        f"/orgs/{current}/activities",
        json={**_BODY, "tags": ["Hoc bong"]},
        headers=owner,
    )
    assert activity.status_code == 201, activity.text
    assert activity.json()["tags"] == [
        {"name": "Hoc bong", "slug": "hoc-bong"}
    ]

    renamed = await client.patch(
        f"/orgs/{source}/tags/hoc-bong",
        json={"name": "HOC BONG"},
        headers=owner,
    )
    assert renamed.status_code == 200, renamed.text
    copied = await client.get(f"/orgs/{current}/tags", headers=owner)
    row = copied.json()["items"][0]
    assert row["name"] == "Hoc bong"
    assert row["slug"] == "hoc-bong"
    again = await client.get(f"/orgs/{current}/tags/owned", headers=owner)
    assert again.json() == []


async def test_member_does_not_see_the_owners_other_orgs(
    client: AsyncClient,
) -> None:
    owner = await _headers(client, "own.mem@example.com", "0903000082")
    member = await _headers(client, "own.mem2@example.com", "0903000083")
    source = await _org(client, owner, "own-hid")
    current = await _org(client, owner, "own-here")
    await client.post(
        f"/orgs/{source}/tags", json={"name": "Y te"}, headers=owner
    )
    invited = await client.post(
        f"/orgs/{current}/members",
        json={"email": "own.mem2@example.com"},
        headers=owner,
    )
    assert invited.status_code == 201, invited.text
    accepted = await client.post(
        f"/orgs/{current}/members/me/accept", headers=member
    )
    assert accepted.status_code == 200, accepted.text
    hidden = await client.get(
        f"/orgs/{current}/tags/owned", headers=member
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json() == []

    outsider = await _headers(client, "own.out@example.com", "0903000084")
    denied = await client.get(
        f"/orgs/{current}/tags/owned", headers=outsider
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "FORBIDDEN"
