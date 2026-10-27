"""Integration tests: public browse feed over real ScyllaDB feeds."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"
HA_NOI = "H" + chr(0xE0) + " N" + chr(0x1ED9) + "i"  # diacritics kept ASCII in source

_BODY = {
    "description": "Clean the beach together",
    "location": "Bai bien",
    "is_remote": False,
    "hours_awarded": 4.0,
}


async def _token(client: AsyncClient, email: str, phone: str) -> str:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "phone": phone,
            "password": PASSWORD,
            "full_name": "Browse Owner",
        },
    )
    assert response.status_code == 201, response.text
    logged = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert logged.status_code == 200, logged.text
    return logged.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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


async def _activity(
    client: AsyncClient,
    headers: dict,
    org_id: str,
    title: str,
    start_at: str,
    **extra: object,
) -> dict:
    created = await client.post(
        f"/orgs/{org_id}/activities",
        json={**_BODY, "title": title, "start_at": start_at, **extra},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()


async def _transition(
    client: AsyncClient, headers: dict, org_id: str, aid: str, status: str
) -> None:
    moved = await client.post(
        f"/orgs/{org_id}/activities/{aid}/status",
        json={"status": status},
        headers=headers,
    )
    assert moved.status_code == 200, moved.text


async def _browse(client: AsyncClient, **params: object) -> dict:
    response = await client.get("/activities/browse", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_browse_tabs_filters_and_seats(client: AsyncClient) -> None:
    owner = _headers(await _token(client, "c.own@example.com", "0903000030"))
    org_id = await _org(client, owner, "browse-club")

    upcoming = await _activity(
        client, owner, org_id, "Ban tinh nguyen", "2030-06-01T08:00:00Z",
        city=HA_NOI, max_participants=5,
    )
    await _transition(client, owner, org_id, upcoming["id"], "published")

    online = await _activity(
        client, owner, org_id, "Day online", "2030-07-01T08:00:00Z",
        is_remote=True,
    )
    await _transition(client, owner, org_id, online["id"], "published")

    await _activity(
        client, owner, org_id, "Ban nhap", "2030-08-01T08:00:00Z"
    )

    done = await _activity(
        client, owner, org_id, "Da ket thuc", "2030-09-01T08:00:00Z"
    )
    await _transition(client, owner, org_id, done["id"], "published")
    await _transition(client, owner, org_id, done["id"], "completed")

    live = await _activity(
        client, owner, org_id, "Dang dien ra", "2030-10-01T08:00:00Z"
    )
    await _transition(client, owner, org_id, live["id"], "published")
    await _transition(client, owner, org_id, live["id"], "ongoing")

    tab = await _browse(client, phase="upcoming")
    titles = [item["title"] for item in tab["items"]]
    assert titles == ["Ban tinh nguyen", "Day online"]
    assert all(item["phase"] == "upcoming" for item in tab["items"])
    assert all(item["org"]["name"] == "Club browse-club" for item in tab["items"])

    assert [i["title"] for i in (await _browse(client, phase="past"))["items"]] == [
        "Da ket thuc"
    ]
    assert [i["title"] for i in (await _browse(client, phase="ongoing"))["items"]] == [
        "Dang dien ra"
    ]

    by_city = await _browse(client, phase="upcoming", city=HA_NOI)
    assert [i["title"] for i in by_city["items"]] == ["Ban tinh nguyen"]
    assert {c["city"]: c["count"] for c in by_city["facets"]["cities"]} == {HA_NOI: 1}

    folded = await _browse(client, phase="upcoming", q="ha noi")
    assert [i["title"] for i in folded["items"]] == ["Ban tinh nguyen"]

    online_only = await _browse(client, phase="upcoming", mode="online")
    assert [i["title"] for i in online_only["items"]] == ["Day online"]

    capped = by_city["items"][0]
    assert capped["max_participants"] == 5
    assert capped["registered_count"] == 0
    assert capped["seats_left"] == 5
    assert online["id"] != capped["id"]
    assert online_only["items"][0]["seats_left"] is None


async def test_browse_validation_and_anonymous_access(client: AsyncClient) -> None:
    rejected = await client.get("/activities/browse", params={"phase": "later"})
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "VALIDATION_ERROR"

    empty = await _browse(client, phase="upcoming", limit=30, offset=0)
    assert set(empty) == {"items", "total", "truncated", "facets", "next_cursor"}


async def test_signed_in_view_follows_the_registration_lifecycle(
    client: AsyncClient,
) -> None:
    owner = _headers(await _token(client, "d.own@example.com", "0903000040"))
    member = _headers(await _token(client, "d.mem@example.com", "0903000041"))
    org_id = await _org(client, owner, "mine-club")
    seated = await _activity(
        client, owner, org_id, "Cho 1 nguoi", "2030-11-01T08:00:00Z",
        max_participants=1,
    )
    aid = seated["id"]
    await _transition(client, owner, org_id, aid, "published")

    applied = await client.post(
        f"/activities/{aid}/registrations", json={}, headers=member
    )
    assert applied.status_code == 201, applied.text
    registration_id = applied.json()["registration_id"]

    mine = await client.get("/activities/browse/mine", headers=member)
    assert mine.status_code == 200, mine.text
    (item,) = mine.json()["items"]
    assert item["id"] == aid
    assert item["my_registration"]["status"] == "pending"
    assert {f["status"]: f["count"] for f in mine.json()["facets"]["my_status"]} == {
        "pending": 1
    }

    briefs = await client.get("/registrations/mine/brief", headers=member)
    assert briefs.status_code == 200, briefs.text
    assert [b["status"] for b in briefs.json()] == ["pending"]

    approved = await client.post(
        f"/activities/{aid}/registrations/{registration_id}/review",
        json={"status": "approved"},
        headers=owner,
    )
    assert approved.status_code == 200, approved.text

    public = await _browse(client, phase="upcoming", q="cho 1 nguoi")
    card = next(i for i in public["items"] if i["id"] == aid)
    assert card["registered_count"] == 1
    assert card["seats_left"] == 0
    assert "my_registration" not in card

    withdrawn = await client.post(
        f"/activities/{aid}/registrations/{registration_id}/cancel",
        headers=member,
    )
    assert withdrawn.status_code == 200, withdrawn.text
    # Withdrawing a seat leaves the activity itself live.
    after = await client.get("/activities/browse/mine", headers=member)
    (withdrawn_row,) = after.json()["items"]
    assert withdrawn_row["phase"] == "upcoming"
    assert withdrawn_row["my_registration"]["status"] == "cancelled"

    # Only the organizer cancelling the activity yields the cancelled phase.
    await _transition(client, owner, org_id, aid, "cancelled")
    cancelled = await client.get("/activities/browse/mine", headers=member)
    (gone,) = cancelled.json()["items"]
    assert gone["phase"] == "cancelled"

    anonymous = await client.get("/activities/browse/mine")
    assert anonymous.status_code == 401


async def test_category_and_tag_facets_follow_real_matches(client: AsyncClient) -> None:
    owner = _headers(await _token(client, "e.own@example.com", "0903000050"))
    org_id = await _org(client, owner, "facet-club")
    env = "0197f6a2-0001-7000-8000-000000000001"  # seeded global category
    edu = "0197f6a2-0001-7000-8000-000000000002"  # seeded global category

    cleanup = await _activity(
        client, owner, org_id, "Don rac", "2030-03-01T08:00:00Z",
        category_id=env, tags=["Moi truong"],
    )
    await _transition(client, owner, org_id, cleanup["id"], "published")
    teach = await _activity(
        client, owner, org_id, "Day hoc", "2030-03-02T08:00:00Z",
        category_id=edu, tags=["Hien mau"],
    )
    await _transition(client, owner, org_id, teach["id"], "published")

    # Typeahead the tag picker uses must surface the canonical slug.
    suggestions = await client.get("/tags", params={"q": "moi"})
    assert suggestions.status_code == 200, suggestions.text
    assert "moi-truong" in [s["slug"] for s in suggestions.json()]

    everything = await _browse(client, phase="upcoming")
    assert {c["category_id"]: c["count"] for c in everything["facets"]["categories"]} == {
        env: 1, edu: 1,
    }
    assert {t["slug"] for t in everything["facets"]["tags"]} == {"moi-truong", "hien-mau"}

    by_tag = await _browse(client, phase="upcoming", tag="moi-truong")
    assert [i["title"] for i in by_tag["items"]] == ["Don rac"]
    # The category facet reflects the tag filter; the tag facet skips its own.
    assert [c["category_id"] for c in by_tag["facets"]["categories"]] == [env]
    assert {t["slug"] for t in by_tag["facets"]["tags"]} == {"moi-truong", "hien-mau"}

    by_category = await _browse(client, phase="upcoming", category_id=edu)
    assert [i["title"] for i in by_category["items"]] == ["Day hoc"]
    assert [t["slug"] for t in by_category["facets"]["tags"]] == ["hien-mau"]
