"""Unit tests for RegistrationService + AttendanceService rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
import uuid_utils

from core.exceptions import (
    AlreadyCheckedInError,
    AlreadyRegisteredError,
    ForbiddenError,
    InvalidRegistrationStateError,
    NotFoundError,
    RegistrationClosedError,
)
from tests.unit.registration_fakes import (
    make_reg_services,
    published_activity,
)


def _setup() -> tuple:
    (
        reg_svc, att_svc, regs, att, activities, orgs, access, users, notes
    ) = make_reg_services()
    owner = uuid_utils.uuid7()
    student = uuid_utils.uuid7()
    org = orgs.create(
        uuid_utils.uuid7(), owner, "Club", "club", "", "club",
        "open", None, None, None, None, "none", datetime.now(UTC),
    )
    activity = published_activity(activities, org.id, owner)
    return (
        reg_svc, att_svc, regs, att, activities, orgs, access, users,
        notes, org, activity, owner, student,
    )


def test_apply_creates_pending_with_token() -> None:
    (svc, _a, regs, _at, _act, _o, _acc, _u, notes,
     _org, activity, _owner, student) = _setup()
    row = svc.apply(activity.id, student, "I can help")
    assert row.status == "pending"
    assert row.checkin_token is not None
    assert regs.history[-1][2] == "pending"
    assert notes.sent == []  # apply does not notify


def test_apply_rejects_draft_activity() -> None:
    (svc, _a, _r, _at, activities, _o, _acc, _u, _n,
     _org, activity, _owner, student) = _setup()
    activity.status = "draft"
    with pytest.raises(RegistrationClosedError):
        svc.apply(activity.id, student, None)


def test_apply_rejects_after_deadline() -> None:
    (svc, _a, _r, _at, _acts, _o, _acc, _u, _n,
     _org, activity, _owner, student) = _setup()
    activity.registration_deadline = datetime.now(UTC) - timedelta(hours=1)
    with pytest.raises(RegistrationClosedError):
        svc.apply(activity.id, student, None)


def test_duplicate_apply_raises_conflict() -> None:
    (svc, _a, _r, _at, _acts, _o, _acc, _u, _n,
     _org, activity, _owner, student) = _setup()
    svc.apply(activity.id, student, None)
    with pytest.raises(AlreadyRegisteredError):
        svc.apply(activity.id, student, None)


def test_review_approve_notify_and_history() -> None:
    (svc, _a, _r, _at, _acts, _o, _acc, users, notes,
     _org, activity, owner, student) = _setup()
    row = svc.apply(activity.id, student, None)
    out = svc.review(activity.id, row.registration_id, owner,
                     "approved", "welcome")
    assert out.status == "approved"
    assert out.reviewed_by == owner
    assert notes.sent and notes.sent[-1][0] == student
    assert users.users.get(student) is None  # no user needed for notify


def test_review_requires_manager() -> None:
    (svc, _a, _r, _at, _acts, _o, access, _u, _n,
     _org, activity, _owner, student) = _setup()
    row = svc.apply(activity.id, student, None)
    with pytest.raises(ForbiddenError):
        svc.review(activity.id, row.registration_id,
                   uuid_utils.uuid7(), "approved", None)
    assert access.audit[-1][2] == "denied"


def test_review_invalid_transition() -> None:
    (svc, _a, _r, _at, _acts, _o, _acc, _u, _n,
     _org, activity, owner, student) = _setup()
    row = svc.apply(activity.id, student, None)
    svc.review(activity.id, row.registration_id, owner, "rejected", None)
    with pytest.raises(InvalidRegistrationStateError):
        svc.review(activity.id, row.registration_id, owner,
                   "approved", None)


def test_waitlisted_can_be_approved() -> None:
    (svc, _a, _r, _at, _acts, _o, _acc, _u, _n,
     _org, activity, owner, student) = _setup()
    row = svc.apply(activity.id, student, None)
    svc.review(activity.id, row.registration_id, owner, "waitlisted", None)
    out = svc.review(activity.id, row.registration_id, owner,
                     "approved", None)
    assert out.status == "approved"


def test_cancel_only_by_applicant() -> None:
    (svc, _a, _r, _at, _acts, _o, _acc, _u, _n,
     _org, activity, _owner, student) = _setup()
    row = svc.apply(activity.id, student, None)
    with pytest.raises(ForbiddenError):
        svc.cancel(activity.id, row.registration_id, uuid_utils.uuid7())
    out = svc.cancel(activity.id, row.registration_id, student)
    assert out.status == "cancelled"


def test_cancel_rejected_registration_fails() -> None:
    (svc, _a, _r, _at, _acts, _o, _acc, _u, _n,
     _org, activity, owner, student) = _setup()
    row = svc.apply(activity.id, student, None)
    svc.review(activity.id, row.registration_id, owner, "rejected", None)
    with pytest.raises(InvalidRegistrationStateError):
        svc.cancel(activity.id, row.registration_id, student)


def test_reapply_after_cancel() -> None:
    (svc, _a, _r, _at, _acts, _o, _acc, _u, _n,
     _org, activity, _owner, student) = _setup()
    row = svc.apply(activity.id, student, None)
    svc.cancel(activity.id, row.registration_id, student)
    again = svc.apply(activity.id, student, "retry")
    assert again.status == "pending"
    assert again.registration_id != row.registration_id


def test_ticket_only_for_applicant() -> None:
    (svc, _a, _r, _at, _acts, _o, _acc, _u, _n,
     _org, activity, _owner, student) = _setup()
    row = svc.apply(activity.id, student, None)
    assert svc.my_ticket(activity.id, row.registration_id, student) is row
    with pytest.raises(ForbiddenError):
        svc.my_ticket(activity.id, row.registration_id, uuid_utils.uuid7())


def test_check_in_marks_attended_once() -> None:
    (svc, att_svc, _r, _at, _acts, _o, _acc, _u, _n,
     _org, activity, owner, student) = _setup()
    row = svc.apply(activity.id, student, None)
    svc.review(activity.id, row.registration_id, owner, "approved", None)
    record = att_svc.check_in(activity.id, row.checkin_token, owner)
    assert record.student_id == student
    assert svc._registrations.get(row.registration_id).status == "attended"
    with pytest.raises(AlreadyCheckedInError):
        att_svc.check_in(activity.id, row.checkin_token, owner)


def test_check_in_pending_registration_fails() -> None:
    (svc, att_svc, _r, _at, _acts, _o, _acc, _u, _n,
     _org, activity, owner, student) = _setup()
    row = svc.apply(activity.id, student, None)
    with pytest.raises(InvalidRegistrationStateError):
        att_svc.check_in(activity.id, row.checkin_token, owner)


def test_check_in_unknown_token_404() -> None:
    (svc, att_svc, _r, _at, _acts, _o, _acc, _u, _n,
     _org, activity, owner, _student) = _setup()
    svc.apply(activity.id, _student, None)
    with pytest.raises(NotFoundError):
        att_svc.check_in(activity.id, uuid_utils.uuid7(), owner)


def test_manual_checkin_and_checkout_hours() -> None:
    (svc, att_svc, _r, _at, _acts, _o, _acc, _u, _n,
     _org, activity, owner, student) = _setup()
    row = svc.apply(activity.id, student, None)
    svc.review(activity.id, row.registration_id, owner, "approved", None)
    record = att_svc.check_in_manual(
        activity.id, row.registration_id, owner
    )
    out = att_svc.check_out(activity.id, record.record_id, owner, 3.5)
    assert out.actual_hours == 3.5
    assert out.checked_out_at is not None
    with pytest.raises(InvalidRegistrationStateError):
        att_svc.check_out(activity.id, record.record_id, owner, None)


def test_checkout_derives_hours_from_duration() -> None:
    (svc, att_svc, _r, att, _acts, _o, _acc, _u, _n,
     _org, activity, owner, student) = _setup()
    row = svc.apply(activity.id, student, None)
    svc.review(activity.id, row.registration_id, owner, "approved", None)
    record = att_svc.check_in_manual(
        activity.id, row.registration_id, owner
    )
    att.rows[record.record_id].scanned_at = (
        datetime.now(UTC) - timedelta(hours=2)
    )
    out = att_svc.check_out(activity.id, record.record_id, owner, None)
    assert out.actual_hours == pytest.approx(2.0, abs=0.01)


def test_attendance_list_requires_manager() -> None:
    (svc, att_svc, _r, _at, _acts, _o, _acc, _u, _n,
     _org, activity, owner, student) = _setup()
    row = svc.apply(activity.id, student, None)
    svc.review(activity.id, row.registration_id, owner, "approved", None)
    att_svc.check_in_manual(activity.id, row.registration_id, owner)
    rows = att_svc.list_attendance(activity.id, owner)
    assert len(rows) == 1
    with pytest.raises(ForbiddenError):
        att_svc.list_attendance(activity.id, uuid_utils.uuid7())
