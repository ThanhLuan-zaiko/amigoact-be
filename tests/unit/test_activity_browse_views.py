"""Unit tests for the signed-in 'my registrations' view and the facets."""

from __future__ import annotations

from datetime import timedelta

from activities.browse_service import BrowseQuery
from core.ids import uuid7
from tests.unit.browse_fakes import (
    CATEGORY_NAMES,
    EDU,
    MOI_TRUONG,
    ENV,
    NOW,
    _brief,
    _row,
    _service,
)

# --- signed-in 'my registrations' view ------------------------------------


def test_mine_lists_only_registered_activities_including_cancelled() -> None:
    joined = _row(title="joined")
    cancelled = _row(title="withdrawn", status="cancelled")
    stranger = _row(title="not mine")
    briefs = {joined.id: _brief("approved"), cancelled.id: _brief("cancelled")}
    result = _service([joined, cancelled, stranger], briefs=briefs).browse_mine(
        uuid7(), BrowseQuery(), NOW
    )
    assert sorted(c.activity.title for c in result.cards) == ["joined", "withdrawn"]
    phases = {c.activity.title: c.phase for c in result.cards}
    assert phases["withdrawn"] == "cancelled"


def test_mine_drops_drafts_even_when_a_brief_exists() -> None:
    draft = _row(title="draft", status="draft")
    result = _service([draft], briefs={draft.id: _brief("pending")}).browse_mine(
        uuid7(), BrowseQuery(), NOW
    )
    assert result.cards == []


def test_mine_status_facet_counts_before_the_status_filter() -> None:
    a = _row(title="a")
    b = _row(title="b")
    briefs = {a.id: _brief("approved"), b.id: _brief("waitlisted")}
    svc = _service([a, b], briefs=briefs)
    everything = svc.browse_mine(uuid7(), BrowseQuery(), NOW)
    assert dict(everything.my_statuses) == {"approved": 1, "waitlisted": 1}
    only = svc.browse_mine(uuid7(), BrowseQuery(my_status="approved"), NOW)
    assert [c.activity.title for c in only.cards] == ["a"]
    assert dict(only.my_statuses) == {"approved": 1, "waitlisted": 1}


def test_mine_order_live_first_then_past_then_cancelled() -> None:
    live = _row(title="live", start_at=NOW + timedelta(days=3))
    past = _row(title="past", start_at=NOW - timedelta(days=4), status="completed")
    gone = _row(title="gone", status="cancelled", start_at=NOW + timedelta(days=1))
    briefs = {live.id: _brief("approved"), past.id: _brief("attended"), gone.id: _brief("cancelled")}
    result = _service([past, gone, live], briefs=briefs).browse_mine(uuid7(), BrowseQuery(), NOW)
    assert [c.activity.title for c in result.cards] == ["live", "past", "gone"]


def test_mine_cards_carry_the_callers_brief() -> None:
    row = _row(title="mine")
    brief = _brief("pending")
    card = _service([row], briefs={row.id: brief}).browse_mine(uuid7(), BrowseQuery(), NOW).cards[0]
    assert card.my_registration == brief



def test_category_facet_skips_its_own_filter() -> None:
    a = _row(title="a", category_id=ENV)
    b = _row(title="b", category_id=EDU)
    svc = _service([a, b], category_names=CATEGORY_NAMES)
    picked = svc.browse(BrowseQuery(category_id=ENV), NOW)
    assert [c.activity.title for c in picked.cards] == ["a"]
    # The other category stays listed so the user can switch to it.
    assert {c.category_id: c.count for c in picked.categories} == {ENV: 1, EDU: 1}


def test_tag_facet_reflects_the_category_filter() -> None:
    a = _row(title="a", category_id=ENV, tag_names=["Moi truong"])
    b = _row(title="b", category_id=EDU, tag_names=["Hien mau"])
    svc = _service([a, b], category_names=CATEGORY_NAMES)
    scoped = svc.browse(BrowseQuery(category_id=ENV), NOW)
    assert [t.slug for t in scoped.tags] == ["moi-truong"]
    everything = svc.browse(BrowseQuery(), NOW)
    assert sorted(t.slug for t in everything.tags) == ["hien-mau", "moi-truong"]


def test_tag_filter_matches_the_normalized_slug() -> None:
    row = _row(title="env", tag_names=[MOI_TRUONG])
    result = _service([row]).browse(BrowseQuery(tag_slug="moi-truong"), NOW)
    assert [c.activity.title for c in result.cards] == ["env"]
    assert result.tags[0].name == MOI_TRUONG


def test_tag_facet_is_capped_to_the_most_used() -> None:
    rows = [_row(title=f"r{i}", tag_names=[f"tag{i}"]) for i in range(55)]
    result = _service(rows).browse(BrowseQuery(), NOW)
    assert len(result.tags) == 50


def test_category_without_catalog_name_is_dropped() -> None:
    orphan = uuid7()
    result = _service([_row(title="x", category_id=orphan)]).browse(BrowseQuery(), NOW)
    assert result.categories == []
    assert [c.activity.title for c in result.cards] == ["x"]
