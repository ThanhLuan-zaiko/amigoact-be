"""Integration tests: community tags over HTTP (amigoact_test)."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"

_BODY = {
    "title": "Green Weekend",
    "description": "Plant trees together",
    "location": "Da Lat",
    "city": "Da Lat",
    "is_remote": False,
    "start_at": "2030-07-01T08:00:00Z",
    "hours_awarded": 3.0,
}


async def _headers(client: AsyncClient, email: str, phone: str) -> dict:
    await client.post(
        "/auth/register",
        json={
            "email": email,
            "phone": phone,
            "password": PASSWORD,
            "full_name": "Tag User",
        },
    )
    logged = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {logged.json()['access_token']}"}


async def _org(client: AsyncClient, headers: dict, slug: str) -> str:
    created = await client.post(
        "/orgs",
        json={
            "name": f"Club {slug}",
            "slug": slug,
            "description": "",
            "kind": "club",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def _publish(
    client: AsyncClient, org_id: str, aid: str, headers: dict
) -> None:
    res = await client.post(
        f"/orgs/{org_id}/activities/{aid}/status",
        json={"status": "published"},
        headers=headers,
    )
    assert res.status_code == 200, res.text


async def test_tag_lifecycle_and_search(client: AsyncClient) -> None:
    owner = await _headers(client, "t.own@example.com", "0903000030")
    org_id = await _org(client, owner, "tag-club")

    created = await client.post(
        f"/orgs/{org_id}/activities",
        json={
            **_BODY,
            "tags": [
                "M\u00f4i tr\u01b0\u1eddng",
                "moi truong",
                "  \u0110\u00e0 L\u1ea1t  ",
                "",
            ],
        },
        headers=owner,
    )
    assert created.status_code == 201, created.text
    tags = created.json()["tags"]
    assert tags == [
        {"name": "M\u00f4i tr\u01b0\u1eddng", "slug": "moi-truong"},
        {"name": "\u0110\u00e0 L\u1ea1t", "slug": "da-lat"},
    ]
    aid = created.json()["id"]

    catalog = await client.get("/tags?q=moi")
    assert catalog.status_code == 200
    rows = catalog.json()
    assert any(
        r["slug"] == "moi-truong"
        and r["name"] == "M\u00f4i tr\u01b0\u1eddng"
        for r in rows
    )
    assert all(set(r.keys()) == {"name", "slug"} for r in rows)

    # Update rewrites both the names and the feed projection.
    updated = await client.patch(
        f"/orgs/{org_id}/activities/{aid}",
        json={**_BODY, "tags": ["Hi\u1ebfn m\u00e1u"]},
        headers=owner,
    )
    assert updated.status_code == 200
    assert updated.json()["tags"] == [
        {"name": "Hi\u1ebfn m\u00e1u", "slug": "hien-mau"}
    ]

    await _publish(client, org_id, aid, owner)
    feed = await client.get("/activities?tag=hien-mau")
    assert any(r["id"] == aid for r in feed.json())
    stale = await client.get("/activities?tag=moi-truong")
    assert all(r["id"] != aid for r in stale.json())


async def test_tags_scoped_per_org_but_feed_is_cross_org(
    client: AsyncClient,
) -> None:
    owner_a = await _headers(client, "t.a@example.com", "0903000031")
    owner_b = await _headers(client, "t.b@example.com", "0903000032")
    org_a = await _org(client, owner_a, "tag-club-a")
    org_b = await _org(client, owner_b, "tag-club-b")

    first = await client.post(
        f"/orgs/{org_a}/activities",
        json={**_BODY, "tags": ["Tr\u1ed3ng r\u1eebng"]},
        headers=owner_a,
    )
    second = await client.post(
        f"/orgs/{org_b}/activities",
        json={**_BODY, "title": "Forest Day", "tags": ["tr\u1ed3ng R\u1eeaNG"]},
        headers=owner_b,
    )
    # Same slug, but each org's catalog keeps its own first spelling.
    assert first.json()["tags"] == [
        {"name": "Tr\u1ed3ng r\u1eebng", "slug": "trong-rung"}
    ]
    assert second.json()["tags"] == [
        {"name": "tr\u1ed3ng R\u1eeaNG", "slug": "trong-rung"}
    ]

    aid_a, aid_b = first.json()["id"], second.json()["id"]
    await _publish(client, org_a, aid_a, owner_a)
    await _publish(client, org_b, aid_b, owner_b)

    feed = await client.get("/activities?tag=trong-rung")
    ids = {r["id"] for r in feed.json()}
    assert {aid_a, aid_b} <= ids

    # Raw display name resolves through the same normalizer.
    folded = await client.get("/activities?tag=TR\u1ed2NG R\u1eeaNG")
    assert {r["id"] for r in folded.json()} >= {aid_a, aid_b}


async def test_tag_and_category_intersection(client: AsyncClient) -> None:
    owner = await _headers(client, "t.c@example.com", "0903000033")
    org_id = await _org(client, owner, "tag-cat-club")

    cats = await client.get("/categories")
    env = next(r for r in cats.json() if r["slug"] == "environment")

    with_cat = await client.post(
        f"/orgs/{org_id}/activities",
        json={**_BODY, "tags": ["B\u00e3i bi\u1ec3n"], "category_id": env["id"]},
        headers=owner,
    )
    without_cat = await client.post(
        f"/orgs/{org_id}/activities",
        json={**_BODY, "title": "No Cat", "tags": ["B\u00e3i bi\u1ec3n"]},
        headers=owner,
    )
    aid_yes = with_cat.json()["id"]
    await _publish(client, org_id, aid_yes, owner)
    await _publish(client, org_id, without_cat.json()["id"], owner)

    both = await client.get(
        f"/activities?tag=bai-bien&category_id={env['id']}"
    )
    ids = {r["id"] for r in both.json()}
    assert aid_yes in ids
    assert without_cat.json()["id"] not in ids


async def test_tagless_activities_still_work(client: AsyncClient) -> None:
    """Backwards compat: no tags field -> empty list, not an error."""
    owner = await _headers(client, "t.d@example.com", "0903000034")
    org_id = await _org(client, owner, "tag-none-club")
    created = await client.post(
        f"/orgs/{org_id}/activities", json=_BODY, headers=owner
    )
    assert created.status_code == 201
    assert created.json()["tags"] == []

    too_many = await client.post(
        f"/orgs/{org_id}/activities",
        json={**_BODY, "tags": [f"t{i}" for i in range(11)]},
        headers=owner,
    )
    assert too_many.status_code == 422

    search = await client.get("/tags")
    assert search.status_code == 200
    assert isinstance(search.json(), list)
