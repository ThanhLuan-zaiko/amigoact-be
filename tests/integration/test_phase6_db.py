"""Integration tests: leaderboard, reviews, prefs, stats, discovery."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_hours_db import (
    _headers,
    _setup_attended,
    _token,
)


async def test_leaderboard_ranks_after_approval(
    client: AsyncClient,
) -> None:
    owner, student, org_id, aid, student_id = await _setup_attended(
        client, "p6a"
    )
    queue = await client.get(
        f"/orgs/{org_id}/hours/pending", headers=owner
    )
    entry_id = queue.json()[0]["entry_id"]
    approved = await client.post(
        f"/hours/{entry_id}/review",
        json={"status": "approved"},
        headers=owner,
    )
    assert approved.status_code == 200, approved.text

    board = await client.get("/leaderboard", params={"term": "all"})
    assert board.status_code == 200, board.text
    entries = board.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["rank"] == 1
    assert entries[0]["total_hours"] == 3.0
    assert entries[0]["student_name"] == "Test User"

    terms = await client.get("/leaderboard/terms")
    assert "all" in terms.json()


async def test_reviews_flow(client: AsyncClient) -> None:
    owner, student, org_id, aid, _sid = await _setup_attended(
        client, "p6b"
    )
    created = await client.post(
        f"/activities/{aid}/reviews",
        json={"rating": 5, "comment": "R\u1ea5t \u00fd ngh\u0129a"},
        headers=student,
    )
    assert created.status_code == 201, created.text
    assert created.json()["student_name"] == "Test User"

    listing = await client.get(f"/activities/{aid}/reviews")
    assert listing.status_code == 200
    body = listing.json()
    assert body["count"] == 1
    assert body["average_rating"] == 5.0
    assert body["items"][0]["comment"] == "R\u1ea5t \u00fd ngh\u0129a"

    authed = await client.get(
        f"/activities/{aid}/reviews", headers=student
    )
    assert authed.json()["can_review"] is False

    dup = await client.post(
        f"/activities/{aid}/reviews",
        json={"rating": 4},
        headers=student,
    )
    assert dup.status_code == 409
    assert dup.json()["code"] == "REVIEW_EXISTS"

    outsider = _headers(
        await _token(client, "o.p6b@example.com", "0903310010")
    )
    denied = await client.post(
        f"/activities/{aid}/reviews",
        json={"rating": 1},
        headers=outsider,
    )
    assert denied.status_code == 400
    assert denied.json()["code"] == "INVALID_REGISTRATION_STATE"


async def test_notification_preferences_mute_type(
    client: AsyncClient,
) -> None:
    owner, student, org_id, aid, _sid = await _setup_attended(
        client, "p6c"
    )
    prefs = await client.get("/notifications/preferences", headers=student)
    assert prefs.status_code == 200
    assert prefs.json()["channels"] == {"inapp": True}
    assert prefs.json()["muted_types"] == []

    updated = await client.put(
        "/notifications/preferences",
        json={"muted_types": ["hours"]},
        headers=student,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["muted_types"] == ["hours"]

    queue = await client.get(
        f"/orgs/{org_id}/hours/pending", headers=owner
    )
    entry_id = queue.json()[0]["entry_id"]
    await client.post(
        f"/hours/{entry_id}/review",
        json={"status": "approved"},
        headers=owner,
    )
    inbox = await client.get("/notifications", headers=student)
    types = {item["type"] for item in inbox.json()["items"]}
    assert "hours" not in types


async def test_org_stats_and_discovery(client: AsyncClient) -> None:
    owner, student, org_id, aid, _sid = await _setup_attended(
        client, "p6d"
    )
    stats = await client.get(f"/orgs/{org_id}/stats", headers=owner)
    assert stats.status_code == 200, stats.text
    body = stats.json()
    assert body["activities_total"] == 1
    assert body["participants_total"] == 1
    assert body["hours_pending"] == 1

    outsider = _headers(
        await _token(client, "o.p6d@example.com", "0903310011")
    )
    denied = await client.get(f"/orgs/{org_id}/stats", headers=outsider)
    assert denied.status_code == 403

    discovery = await client.get("/activities/discovery")
    assert discovery.status_code == 200, discovery.text
    feed = discovery.json()
    featured_ids = {row["id"] for row in feed["featured"]}
    assert aid in featured_ids or feed["featured"] != []
    assert "categories" in feed
