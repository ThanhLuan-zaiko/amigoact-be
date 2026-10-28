"""Integration tests: membership form and application stores on amigoact_test."""

from __future__ import annotations

from datetime import timezone

from core.ids import uuid7
from core.security import utcnow
from orgs.application_repository import CqlApplicationStore, CqlMembershipFormStore


def test_form_replace_keeps_display_order(clean_tables: str) -> None:
    store = CqlMembershipFormStore()
    org_id = uuid7()
    first, second = uuid7(), uuid7()
    store.replace_form(
        org_id,
        [(first, "Why?", "textarea", True, "[]", False), (second, "Phone?", "text", False, "[]", False)],
    )
    rows = store.list_form(org_id)
    assert [(row.label, row.position) for row in rows] == [("Why?", 0), ("Phone?", 1)]

    store.replace_form(org_id, [(second, "Phone?", "text", False, "[]", False)])
    rows = store.list_form(org_id)
    assert [(row.question_id, row.position) for row in rows] == [(second, 0)]


def test_application_put_overwrites_previous_submission(clean_tables: str) -> None:
    store = CqlApplicationStore()
    org_id, user_id = uuid7(), uuid7()
    store.put(org_id, user_id, '{"a": "first"}', utcnow())
    store.put(org_id, user_id, '{"a": "second"}', utcnow())
    stored = store.get(org_id, user_id)
    assert stored is not None
    assert stored.answers == '{"a": "second"}'
    assert store.get(org_id, uuid7()) is None


def test_mark_rejected_stamps_time_and_new_submission_clears_it(clean_tables: str) -> None:
    store = CqlApplicationStore()
    org_id, user_id = uuid7(), uuid7()
    store.put(org_id, user_id, "{}", utcnow())
    assert store.get(org_id, user_id).rejected_at is None
    rejected_at = utcnow()
    store.mark_rejected(org_id, user_id, rejected_at)
    stored = store.get(org_id, user_id)
    assert stored is not None and stored.rejected_at is not None
    # The driver returns naive UTC wall time; pin the zone before comparing instants.
    read_back = stored.rejected_at.replace(tzinfo=timezone.utc)
    assert abs(read_back.timestamp() - rejected_at.timestamp()) < 1
    store.put(org_id, user_id, "{}", utcnow())
    assert store.get(org_id, user_id).rejected_at is None
