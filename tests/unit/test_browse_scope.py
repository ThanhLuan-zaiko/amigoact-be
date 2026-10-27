"""Browse service rules: organization scope, cursors, detail card and quick sign-up."""

from __future__ import annotations

from datetime import timedelta

import pytest

from activities.browse_service import BrowseQuery
from activities.browse_window import InvalidCursorError
from core.exceptions import NotFoundError
from core.ids import uuid7
from tests.unit.browse_fakes import (
    NOW,
    ORG,
    FakeIndex,
    FakeOrgs,
    FakeQuick,
    _brief,
    _org,
    _row,
    _service,
)


def test_public_plan_carries_the_date_range_and_no_scope() -> None:
    index = FakeIndex([_row()])
    service = _service([], index=index)
    service.browse(
        BrowseQuery(
            starts_from=NOW + timedelta(days=1),
            starts_to=NOW + timedelta(days=9),
        ),
        now=NOW,
    )
    (plan,) = index.plans
    assert plan.org_id is None
    assert plan.cursor is None
    assert plan.starts_from == NOW + timedelta(days=1)
    assert plan.starts_to == NOW + timedelta(days=9)


def test_unknown_org_slug_answers_empty_without_reading_the_index() -> None:
    index = FakeIndex([_row()])
    service = _service([], index=index)
    result = service.browse(BrowseQuery(org_slug="missing"), now=NOW)
    assert result.cards == []
    assert result.total == 0
    assert index.plans == []


def test_hidden_org_slug_answers_empty() -> None:
    index = FakeIndex([_row()])
    service = _service(
        [], index=index, orgs=FakeOrgs(_org(status="suspended"))
    )
    assert service.browse(BrowseQuery(org_slug="clb-xanh"), now=NOW).cards == []
    assert index.plans == []


def test_org_scope_plans_the_organization_feed() -> None:
    index = FakeIndex([_row(org_id=ORG)])
    service = _service([], index=index, orgs=FakeOrgs(_org()))
    service.browse(BrowseQuery(org_slug="clb-xanh"), now=NOW)
    (plan,) = index.plans
    assert plan.org_id == ORG


def test_truncated_window_offers_a_cursor_that_resumes_in_scope() -> None:
    index = FakeIndex([_row()], truncated=True)
    service = _service([], index=index, orgs=FakeOrgs(_org()))
    first = service.browse(BrowseQuery(org_slug="clb-xanh"), now=NOW)
    assert first.next_cursor is not None
    service.browse(
        BrowseQuery(org_slug="clb-xanh", cursor=first.next_cursor), now=NOW
    )
    resumed = index.plans[-1].cursor
    assert resumed is not None
    assert resumed.org_id == str(ORG)


def test_cursor_from_another_scope_is_rejected() -> None:
    index = FakeIndex([_row()], truncated=True)
    service = _service([], index=index, orgs=FakeOrgs(_org()))
    first = service.browse(BrowseQuery(), now=NOW)
    with pytest.raises(InvalidCursorError):
        service.browse(
            BrowseQuery(org_slug="clb-xanh", cursor=first.next_cursor), now=NOW
        )


def test_complete_window_offers_no_cursor() -> None:
    service = _service([_row()])
    assert service.browse(BrowseQuery(), now=NOW).next_cursor is None


def test_card_for_serves_a_public_activity() -> None:
    row = _row()
    card = _service([row]).card_for(row.id, now=NOW)
    assert card.activity is row
    assert card.phase == "upcoming"


@pytest.mark.parametrize(
    "overrides",
    [{"status": "draft"}, {"status": "cancelled"}, {"deleted_at": NOW}],
)
def test_card_for_hides_drafts_cancelled_and_deleted(overrides) -> None:  # noqa: ANN001
    row = _row(**overrides)
    with pytest.raises(NotFoundError):
        _service([row]).card_for(row.id, now=NOW)


def test_card_for_unknown_activity_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        _service([]).card_for(uuid7(), now=NOW)


def test_card_for_hides_cards_of_hidden_orgs() -> None:
    row = _row()
    service = _service([row], orgs=FakeOrgs(_org(status="suspended")))
    with pytest.raises(NotFoundError):
        service.card_for(row.id, now=NOW)


def test_card_for_carries_the_quick_flag() -> None:
    row = _row()
    card = _service([row], quick=FakeQuick()).card_for(row.id, now=NOW)
    assert card.quick_apply is True


def test_quick_apply_flags_open_activities_without_form_or_slots() -> None:
    plain = _row(title="Plain")
    needy = _row(title="Needs a form")
    late = _row(registration_deadline=NOW - timedelta(hours=1))
    probe = FakeQuick(needing={needy.id})
    service = _service([plain, needy, late], quick=probe)
    result = service.browse(BrowseQuery(), now=NOW)
    flags = {card.activity.id: card.quick_apply for card in result.cards}
    assert flags == {plain.id: True, needy.id: False, late.id: False}


def test_closed_cards_cost_no_probe() -> None:
    late = _row(registration_deadline=NOW - timedelta(hours=1))
    probe = FakeQuick()
    _service([late], quick=probe).browse(BrowseQuery(), now=NOW)
    assert late.id not in probe.asked


def test_mine_view_honours_the_date_range() -> None:
    early = _row(start_at=NOW + timedelta(days=2))
    late = _row(start_at=NOW + timedelta(days=20))
    briefs = {early.id: _brief("approved"), late.id: _brief("approved")}
    service = _service([early, late], briefs=briefs)
    result = service.browse_mine(
        uuid7(),
        BrowseQuery(starts_from=NOW + timedelta(days=10)),
        now=NOW,
    )
    assert [card.activity.id for card in result.cards] == [late.id]
