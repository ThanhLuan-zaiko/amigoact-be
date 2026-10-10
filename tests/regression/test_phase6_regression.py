"""Regression locks: Phase 6 response shapes and route wiring."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_hours_db import (
    _headers,
    _setup_attended,
)


async def test_leaderboard_contract(client: AsyncClient) -> None:
    """Freeze the leaderboard payload shape for the FE."""
    owner, _s, org_id, _a, _sid = await _setup_attended(client, "r6a")
    queue = await client.get(
        f"/orgs/{org_id}/hours/pending", headers=owner
    )
    await client.post(
        f"/hours/{queue.json()[0]['entry_id']}/review",
        json={"status": "approved"},
        headers=owner,
    )
    board = await client.get("/leaderboard")
    assert board.status_code == 200
    assert set(board.json()) == {"term", "entries"}
    assert set(board.json()["entries"][0]) == {
        "student_id",
        "student_name",
        "total_hours",
        "rank",
    }


async def test_review_list_contract(client: AsyncClient) -> None:
    """Freeze review list shape including the eligibility flag."""
    _o, student, _g, aid, _sid = await _setup_attended(client, "r6b")
    await client.post(
        f"/activities/{aid}/reviews",
        json={"rating": 4},
        headers=student,
    )
    listing = await client.get(f"/activities/{aid}/reviews")
    assert listing.status_code == 200
    body = listing.json()
    assert set(body) == {
        "items",
        "average_rating",
        "count",
        "can_review",
    }
    assert set(body["items"][0]) == {
        "review_id",
        "activity_id",
        "student_id",
        "student_name",
        "rating",
        "comment",
        "created_at",
    }


async def test_preferences_and_stats_contract(client: AsyncClient) -> None:
    """Freeze prefs roundtrip and org stats payload shapes."""
    owner, student, org_id, _a, _sid = await _setup_attended(
        client, "r6c"
    )
    prefs = await client.put(
        "/notifications/preferences",
        json={"muted_types": ["hours"], "channels": {"email": True}},
        headers=student,
    )
    assert prefs.status_code == 200
    assert set(prefs.json()) == {"channels", "muted_types"}
    assert prefs.json()["muted_types"] == ["hours"]

    stats = await client.get(f"/orgs/{org_id}/stats", headers=owner)
    assert stats.status_code == 200
    assert set(stats.json()) == {
        "activities_total",
        "members_total",
        "participants_total",
        "hours_approved",
        "hours_pending",
        "certificates_issued",
    }

    discovery = await client.get("/activities/discovery")
    assert discovery.status_code == 200
    assert set(discovery.json()) == {
        "featured",
        "upcoming",
        "categories",
    }
