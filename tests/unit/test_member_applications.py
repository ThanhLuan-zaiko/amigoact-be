"""Unit tests for membership applications: form, apply, review, read-back."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from core.exceptions import (
    AlreadyMemberError,
    ForbiddenError,
    InvalidMemberStateError,
    MemberNotFoundError,
    TooManyRequestsError,
)
from core.exceptions_applications import (
    AlreadyAppliedError,
    AnswerRequiredError,
    ApplicationCooldownError,
    ApplicationNotOpenError,
    ApplicationRequiredError,
    InvitePendingError,
)
from core.security import utcnow
from orgs import member_applications
from tests.unit.application_fakes import FakeLimiter, FakeNotifications
from tests.unit.member_fakes import NOW, _make_admin, _new_user, _service, _uid

OPTIONAL_NOTE = [("Note?", "text", False, [], False)]
REQUIRED_WHY = [("Why?", "textarea", True, [], False), ("Phone?", "text", False, [], False)]


def _publish(service, org_id, owner, questions=None):  # noqa: ANN001, ANN202
    """Owner publishes the form; returns the stored question rows."""
    return service.replace_membership_form(org_id, owner, questions or OPTIONAL_NOTE)


def test_open_org_refuses_applications() -> None:
    service, _, _, users, _, org_id, _ = _service("open")
    applicant = _new_user(users, "a@example.com")
    with pytest.raises(ApplicationNotOpenError):
        service.apply_to_org(org_id, applicant, {})


def test_join_on_review_org_points_to_apply() -> None:
    service, _, _, users, _, org_id, _ = _service("review")
    applicant = _new_user(users, "a@example.com")
    with pytest.raises(ApplicationRequiredError):
        service.join_org(org_id, applicant)


def test_apply_stores_known_answers_and_sets_applied() -> None:
    service, _, members, users, _, org_id, owner = _service("review")
    why, phone = _publish(service, org_id, owner, REQUIRED_WHY)
    applicant = _new_user(users, "a@example.com")
    snap = service.apply_to_org(
        org_id,
        applicant,
        {str(why.question_id): "  Helping kids  ", str(phone.question_id): "0901", "x": "y"},
    )
    assert snap.status == "applied"
    assert members.get(org_id, applicant).status == "applied"
    stored = json.loads(service._applications.get(org_id, applicant).answers)
    assert stored == {str(why.question_id): "Helping kids", str(phone.question_id): "0901"}
    assert service._events.roster[-1][1] == "applied"


def test_apply_requires_required_answers() -> None:
    service, _, _, users, _, org_id, owner = _service("review")
    why, phone = _publish(service, org_id, owner, REQUIRED_WHY)
    applicant = _new_user(users, "a@example.com")
    with pytest.raises(AnswerRequiredError):
        service.apply_to_org(org_id, applicant, {str(phone.question_id): "0901"})


def test_apply_refused_while_pending_invited_or_member() -> None:
    service, _, members, users, _, org_id, owner = _service("review")
    _publish(service, org_id, owner)
    pending = _new_user(users, "p@example.com")
    service.apply_to_org(org_id, pending, {})
    with pytest.raises(AlreadyAppliedError):
        service.apply_to_org(org_id, pending, {})
    invited = _new_user(users, "i@example.com")
    service.invite_member(org_id, owner, "i@example.com")
    with pytest.raises(InvitePendingError):
        service.apply_to_org(org_id, invited, {})
    member = _new_user(users, "m@example.com")
    members.put(org_id, member, "active", NOW)
    with pytest.raises(AlreadyMemberError):
        service.apply_to_org(org_id, member, {})


def test_owner_approves_applicant_and_applicant_is_notified() -> None:
    service, _, members, users, access, org_id, owner = _service("review")
    _publish(service, org_id, owner)
    applicant = _new_user(users, "a@example.com")
    service.apply_to_org(org_id, applicant, {})
    snap = service.review_application(org_id, owner, applicant, approve=True)
    assert snap.status == "active"
    assert members.get(org_id, applicant).status == "active"
    assert service._events.inbox[-1][1] == "approved"
    assert access.audit[-1] == ("member.approve", applicant, "allowed")


def test_reject_starts_seven_day_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _, members, users, _, org_id, owner = _service("review")
    _publish(service, org_id, owner)
    applicant = _new_user(users, "a@example.com")
    service.apply_to_org(org_id, applicant, {})
    snap = service.review_application(org_id, owner, applicant, approve=False)
    assert snap.status == "left"
    assert service._events.inbox[-1][1] == "rejected"
    with pytest.raises(ApplicationCooldownError):
        service.apply_to_org(org_id, applicant, {})
    later = utcnow() + timedelta(days=7, minutes=1)
    monkeypatch.setattr(member_applications, "utcnow", lambda: later)
    again = service.apply_to_org(org_id, applicant, {})
    assert again.status == "applied"
    assert members.get(org_id, applicant).status == "applied"


def test_attempts_are_capped_per_applicant_and_refused_ones_count() -> None:
    service, _, _, users, _, org_id, owner = _service("review")
    _publish(service, org_id, owner)
    service._limiter = FakeLimiter()
    applicant = _new_user(users, "a@example.com")
    service.apply_to_org(org_id, applicant, {})
    for _ in range(4):
        with pytest.raises(AlreadyAppliedError):
            service.apply_to_org(org_id, applicant, {})
    with pytest.raises(TooManyRequestsError):
        service.apply_to_org(org_id, applicant, {})


def test_owner_gets_one_new_application_ping_per_window() -> None:
    service, _, _, users, _, org_id, owner = _service("review")
    _publish(service, org_id, owner)
    service._limiter = FakeLimiter()
    service._notifications = FakeNotifications()
    for email in ("a@example.com", "b@example.com", "c@example.com"):
        service.apply_to_org(org_id, _new_user(users, email), {})
    pings = [item for item in service._notifications.sent if item[0] == owner]
    assert len(pings) == 1
    assert len(service._events.roster) >= 3


def test_review_needs_invite_permission() -> None:
    service, _, members, users, access, org_id, owner = _service("review")
    _publish(service, org_id, owner)
    applicant = _new_user(users, "a@example.com")
    service.apply_to_org(org_id, applicant, {})
    plain = _new_user(users, "plain@example.com")
    members.put(org_id, plain, "active", NOW)
    with pytest.raises(ForbiddenError):
        service.review_application(org_id, plain, applicant, approve=True)
    reviewer = _new_user(users, "admin@example.com")
    _make_admin(members, access, org_id, reviewer)
    snap = service.review_application(org_id, reviewer, applicant, approve=True)
    assert snap.status == "active"


def test_review_requires_a_pending_application() -> None:
    service, _, _, users, _, org_id, owner = _service("review")
    stranger = _new_user(users, "s@example.com")
    with pytest.raises(InvalidMemberStateError):
        service.review_application(org_id, owner, stranger, approve=True)


def test_form_edit_is_manager_only_and_keeps_order() -> None:
    service, _, members, users, _, org_id, owner = _service("review")
    plain = _new_user(users, "plain@example.com")
    members.put(org_id, plain, "active", NOW)
    with pytest.raises(ForbiddenError):
        service.replace_membership_form(org_id, plain, OPTIONAL_NOTE)
    rows = _publish(service, org_id, owner, [("Q1", "text", True, [], False), ("Q2", "choice", False, [], False)])
    assert [row.label for row in rows] == ["Q1", "Q2"]
    assert [row.field_type for row in service.list_membership_form(org_id)] == [
        "text",
        "choice",
    ]


def test_read_application_returns_submission_for_reviewers() -> None:
    service, _, _, users, _, org_id, owner = _service("review")
    (note,) = _publish(service, org_id, owner)
    applicant = _new_user(users, "a@example.com")
    service.apply_to_org(org_id, applicant, {str(note.question_id): "hello"})
    stored, questions = service.get_application(org_id, owner, applicant)
    assert json.loads(stored.answers) == {str(note.question_id): "hello"}
    assert [q.label for q in questions] == ["Note?"]
    with pytest.raises(MemberNotFoundError):
        service.get_application(org_id, owner, _uid())


def test_applicant_withdraws_through_self_leave_and_can_reapply() -> None:
    service, _, members, users, _, org_id, owner = _service("review")
    _publish(service, org_id, owner)
    applicant = _new_user(users, "a@example.com")
    service.apply_to_org(org_id, applicant, {})
    service.remove_member(org_id, applicant, applicant)
    assert members.get(org_id, applicant).status == "left"
    assert service.apply_to_org(org_id, applicant, {}).status == "applied"
