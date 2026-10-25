"""Unit tests for the browse feed: pure rules and the service pipeline."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from activities.browse_filters import (
    DEFAULT_DURATION,
    classify_phase,
    is_registration_open,
    matches_query,
    utc_naive,
)
from activities.browse_service import BrowseQuery
from core.ids import uuid7
from orgs.listing import fold_search_text
from tests.unit.browse_fakes import (
    HA_NOI,
    NOW,
    ORG,
    FakeOrgs,
    _org,
    _row,
    _service,
)

# --- pure rules -----------------------------------------------------------


def test_classify_upcoming_ongoing_past_boundaries() -> None:
    future = NOW + timedelta(hours=1)
    assert classify_phase("published", future, None, NOW) == "upcoming"
    started = NOW - timedelta(minutes=30)
    assert classify_phase("published", started, None, NOW) == "ongoing"
    closed = NOW - DEFAULT_DURATION - timedelta(minutes=1)
    assert classify_phase("published", closed, None, NOW) == "past"


def test_classify_uses_end_at_when_present() -> None:
    started = NOW - timedelta(hours=10)
    later = NOW + timedelta(hours=2)
    assert classify_phase("published", started, later, NOW) == "ongoing"


def test_classify_status_overrides_and_hidden_states() -> None:
    assert classify_phase("completed", NOW, None, NOW) == "past"
    assert classify_phase("ongoing", NOW + timedelta(days=1), None, NOW) == "ongoing"
    assert classify_phase("draft", NOW, None, NOW) is None
    assert classify_phase("cancelled", NOW, None, NOW) is None
    assert classify_phase("published", None, None, NOW) is None


def test_registration_open_rules() -> None:
    assert is_registration_open("published", None, "upcoming", NOW) is True
    assert is_registration_open("published", NOW - timedelta(days=1), "upcoming", NOW) is False
    assert is_registration_open("published", None, "past", NOW) is False
    assert is_registration_open("cancelled", None, "upcoming", NOW) is False


def test_search_folds_diacritics_both_ways() -> None:
    term = fold_search_text("ha noi")
    assert matches_query(term, [HA_NOI])
    assert not matches_query(fold_search_text("da nang"), [HA_NOI])


def test_utc_naive_converts_aware_and_keeps_naive() -> None:
    aware = datetime(2026, 10, 25, 16, 0, tzinfo=timezone(timedelta(hours=7)))
    assert utc_naive(aware) == datetime(2026, 10, 25, 9, 0)
    assert utc_naive(NOW) == NOW
    assert utc_naive(None) is None


# --- public pipeline ------------------------------------------------------


def test_hidden_states_never_reach_the_public_feed() -> None:
    org_gone = uuid7()
    rows = [
        _row(title="visible"),
        _row(status="draft"),
        _row(status="cancelled"),
        _row(deleted_at=NOW),
        _row(org_id=org_gone),
    ]
    orgs = FakeOrgs(_org(), _org(id=org_gone, status="suspended"))
    result = _service(rows, orgs).browse(BrowseQuery(), now=NOW)
    assert [card.activity.title for card in result.cards] == ["visible"]


def test_phase_tabs_split_upcoming_ongoing_and_past() -> None:
    upcoming = _row(title="soon")
    ongoing = _row(title="now", start_at=NOW - timedelta(minutes=5))
    done = _row(title="done", start_at=NOW - timedelta(days=3), status="completed")
    rows = [upcoming, ongoing, done]
    svc = _service(rows)
    assert [c.activity.title for c in svc.browse(BrowseQuery(phase="upcoming"), NOW).cards] == ["soon"]
    assert [c.activity.title for c in svc.browse(BrowseQuery(phase="ongoing"), NOW).cards] == ["now"]
    assert [c.activity.title for c in svc.browse(BrowseQuery(phase="past"), NOW).cards] == ["done"]


def test_upcoming_sorts_soonest_first_and_past_newest_first() -> None:
    later = _row(title="later", start_at=NOW + timedelta(days=9))
    sooner = _row(title="sooner", start_at=NOW + timedelta(days=2))
    svc = _service([later, sooner])
    titles = [c.activity.title for c in svc.browse(BrowseQuery(), NOW).cards]
    assert titles == ["sooner", "later"]
    old_a = _row(title="a", start_at=NOW - timedelta(days=5), status="completed")
    old_b = _row(title="b", start_at=NOW - timedelta(days=2), status="completed")
    past = _service([old_a, old_b]).browse(BrowseQuery(phase="past"), NOW)
    assert [c.activity.title for c in past.cards] == ["b", "a"]


def test_search_city_and_facets_ignore_the_city_filter() -> None:
    hanoi = _row(title="Ban tinh nguyen", city=HA_NOI)
    hcm = _row(title="Don rac", city="Ho Chi Minh")
    svc = _service([hanoi, hcm])
    by_name = svc.browse(BrowseQuery(q="tinh nguyen"), NOW)
    assert [c.activity.title for c in by_name.cards] == ["Ban tinh nguyen"]
    by_city = svc.browse(BrowseQuery(city="ha noi"), NOW)
    assert [c.activity.title for c in by_city.cards] == ["Ban tinh nguyen"]
    # Facets reflect every other filter but not the city itself.
    assert dict(by_city.cities) == {HA_NOI: 1, "Ho Chi Minh": 1}


def test_mode_and_registration_open_filters() -> None:
    online = _row(title="online", is_remote=True)
    onsite = _row(title="onsite", is_remote=False)
    closed = _row(title="closed", registration_deadline=NOW - timedelta(days=1))
    svc = _service([online, onsite, closed])
    assert [c.activity.title for c in svc.browse(BrowseQuery(mode="online"), NOW).cards] == ["online"]
    open_only = svc.browse(BrowseQuery(registration_open_only=True), NOW)
    assert sorted(c.activity.title for c in open_only.cards) == ["online", "onsite"]


def test_paging_reports_total_and_passes_truncation_through() -> None:
    rows = [_row(title=f"t{i}", start_at=NOW + timedelta(days=i + 1)) for i in range(5)]
    svc = _service(rows, truncated=True)
    page = svc.browse(BrowseQuery(limit=2, offset=2), NOW)
    assert page.total == 5
    assert page.truncated is True
    assert [c.activity.title for c in page.cards] == ["t2", "t3"]


def test_seats_reflect_capacity_and_unlimited_stays_null() -> None:
    capped = _row(title="capped", max_participants=10)
    open_ended = _row(title="open")
    seats = {capped.id: 4}
    result = _service([capped, open_ended], seats=seats).browse(BrowseQuery(), NOW)
    by_title = {c.activity.title: c for c in result.cards}
    assert by_title["capped"].registered_count == 4
    assert by_title["capped"].seats_left == 6
    assert by_title["open"].registered_count is None
    assert by_title["open"].seats_left is None


def test_each_distinct_org_is_read_once_per_request() -> None:
    rows = [_row(title=f"x{i}") for i in range(4)]
    orgs = FakeOrgs(_org())
    _service(rows, orgs).browse(BrowseQuery(), NOW)
    assert orgs.calls == [ORG]


def test_cover_prefers_cover_role_then_first_image() -> None:
    row = _row(title="cover")
    entries = {
        row.id: [
            SimpleNamespace(asset_id=uuid7(), role="gallery", position=0),
            SimpleNamespace(asset_id=uuid7(), role="cover", position=1),
        ]
    }
    cover_asset = entries[row.id][1].asset_id
    gallery_asset = entries[row.id][0].asset_id
    assets = {
        cover_asset: SimpleNamespace(file_url="c.jpg", mime="image/jpeg", deleted_at=None, upload_status="active"),
        gallery_asset: SimpleNamespace(file_url="g.jpg", mime="image/jpeg", deleted_at=None, upload_status="active"),
    }
    card = _service([row], entries=entries, assets=assets).browse(BrowseQuery(), NOW).cards[0]
    assert card.cover_url == "/media/c.jpg"


def test_excerpt_is_flattened_and_capped() -> None:
    long_text = "word " * 80
    card = _service([_row(description=long_text)]).browse(BrowseQuery(), NOW).cards[0]
    assert len(card.excerpt) <= 160
    assert card.excerpt.endswith("...")
    assert "  " not in card.excerpt


