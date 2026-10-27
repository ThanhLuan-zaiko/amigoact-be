"""Integration tests: detail card, organization scope, cursor windows and quick sign-up."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.integration.test_activity_browse_db import (
    _activity,
    _browse,
    _headers,
    _org,
    _token,
    _transition,
)


async def test_activity_card_serves_one_public_activity(client: AsyncClient) -> None:
    owner = _headers(await _token(client, "card.own@example.com", "0903700101"))
    org_id = await _org(client, owner, "card-club")
    row = await _activity(
        client, owner, org_id, "The card", "2030-05-01T08:00:00Z",
        max_participants=4,
    )
    await _transition(client, owner, org_id, row["id"], "published")

    card = await client.get(f"/activities/{row['id']}/card")
    assert card.status_code == 200, card.text
    body = card.json()
    assert body["id"] == row["id"]
    assert body["phase"] == "upcoming"
    assert body["org"]["slug"] == "card-club"
    assert body["seats_left"] == 4
    assert body["quick_apply"] is True
    assert "my_registration" not in body

    draft = await _activity(
        client, owner, org_id, "Draft card", "2030-05-02T08:00:00Z"
    )
    hidden = await client.get(f"/activities/{draft['id']}/card")
    assert hidden.status_code == 404


async def test_org_scope_and_date_range_read_one_organization(
    client: AsyncClient,
) -> None:
    owner = _headers(await _token(client, "scope.own@example.com", "0903700102"))
    first_org = await _org(client, owner, "scope-first")
    second_org = await _org(client, owner, "scope-second")
    first = await _activity(
        client, owner, first_org, "Scope A", "2031-03-01T08:00:00Z"
    )
    await _transition(client, owner, first_org, first["id"], "published")
    second = await _activity(
        client, owner, second_org, "Scope B", "2031-03-02T08:00:00Z"
    )
    await _transition(client, owner, second_org, second["id"], "published")

    scoped = await _browse(client, org="scope-first", phase="upcoming")
    assert [item["title"] for item in scoped["items"]] == ["Scope A"]

    unknown = await _browse(client, org="no-such-club", phase="upcoming")
    assert unknown["items"] == []
    assert unknown["total"] == 0

    later = await _browse(
        client, org="scope-first", phase="upcoming",
        starts_from="2031-03-05T00:00:00Z",
    )
    assert later["items"] == []


async def test_cursor_walks_every_window_without_gaps(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two rows per window forces several cursor hops over five activities.
    monkeypatch.setattr("activities.browse_repository.SCAN_LIMIT", 2)
    owner = _headers(await _token(client, "walk.own@example.com", "0903700103"))
    org_id = await _org(client, owner, "walk-club")
    ids: list[str] = []
    for day in range(1, 6):
        row = await _activity(
            client, owner, org_id, f"Walk {day}", f"2032-04-0{day}T08:00:00Z"
        )
        await _transition(client, owner, org_id, row["id"], "published")
        ids.append(row["id"])

    seen: list[str] = []
    windows = 0
    token: str | None = None
    for _ in range(10):
        params: dict[str, object] = {
            "phase": "upcoming",
            "starts_from": "2032-04-01T00:00:00Z",
            "starts_to": "2032-05-01T00:00:00Z",
            "limit": 30,
        }
        if token is not None:
            params["cursor"] = token
        page = await _browse(client, **params)
        windows += 1
        seen.extend(item["id"] for item in page["items"])
        token = page["next_cursor"]
        if token is None:
            break
    assert windows > 1
    assert token is None
    assert sorted(seen) == sorted(ids)


async def test_quick_apply_turns_off_when_the_form_asks_questions(
    client: AsyncClient,
) -> None:
    owner = _headers(await _token(client, "quick.own@example.com", "0903700104"))
    org_id = await _org(client, owner, "quick-club")
    row = await _activity(
        client, owner, org_id, "Quick sign up", "2033-06-01T08:00:00Z"
    )
    await _transition(client, owner, org_id, row["id"], "published")
    window = {
        "phase": "upcoming",
        "starts_from": "2033-06-01T00:00:00Z",
        "starts_to": "2033-06-02T00:00:00Z",
    }
    before = await _browse(client, **window)
    assert before["items"][0]["quick_apply"] is True

    formed = await client.put(
        f"/orgs/{org_id}/activities/{row['id']}/form",
        json={"questions": [{"label": "Why?", "field_type": "text", "required": True}]},
        headers=owner,
    )
    assert formed.status_code == 200, formed.text
    after = await _browse(client, **window)
    assert after["items"][0]["quick_apply"] is False
