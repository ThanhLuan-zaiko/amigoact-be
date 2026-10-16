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
from registrations.attendance_service import AttendanceService
from tests.unit.registration_fakes import (
    FakeAttendanceEvents,
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
    assert regs.history[-1].to_status == "pending"
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


def test_history_visible_to_applicant_and_manager() -> None:
    (svc, _a, _r, _at, _acts, _o, _acc, _u, _n,
     _org, activity, owner, student) = _setup()
    row = svc.apply(activity.id, student, None)
    svc.review(activity.id, row.registration_id, owner, "approved", "ok")
    entries = svc.history(activity.id, row.registration_id, student)
    assert [h.to_status for h in entries] == ["approved", "pending"]
    assert svc.history(activity.id, row.registration_id, owner) == entries
    with pytest.raises(ForbiddenError):
        svc.history(activity.id, row.registration_id, uuid_utils.uuid7())


def test_history_missing_registration_404() -> None:
    (svc, _a, _r, _at, _acts, _o, _acc, _u, _n,
     _org, activity, _owner, student) = _setup()
    with pytest.raises(NotFoundError):
        svc.history(activity.id, uuid_utils.uuid7(), student)


def _full_activity_setup():
    """One-slot activity: owner approved, second applicant waitlisted."""
    (
        reg_svc, att_svc, regs, att, activities, orgs, access, users,
        notes, org, activity, owner, student,
    ) = _setup()
    activity.max_participants = 1
    first = reg_svc.apply(activity.id, owner, None)
    reg_svc.review(activity.id, first.registration_id, owner,
                   "approved", None)
    second = reg_svc.apply(activity.id, student, None)
    return (
        reg_svc, regs, notes, activity, owner, student, first, second,
    )


def test_apply_waitlists_when_full() -> None:
    (svc, regs, _n, _activity, _owner, _st, _first, second) = (
        _full_activity_setup()
    )
    assert second.status == "waitlisted"
    waiting = regs.list_waitlist(second.activity_id, "waiting")
    assert [e.student_id for e in waiting] == [second.student_id]


def test_cancel_approved_promotes_next_waitlisted() -> None:
    (svc, regs, notes, activity, owner, student, first, second) = (
        _full_activity_setup()
    )
    svc.cancel(activity.id, first.registration_id, owner)
    out = regs.get(second.registration_id)
    assert out.status == "approved"
    assert out.review_note == "promoted from waitlist"
    assert regs.list_waitlist(activity.id, "waiting") == []
    assert [n[0] for n in notes.sent] == [owner, student]
    hist = regs.list_history(second.registration_id)
    assert [h.to_status for h in hist] == [
        "approved", "waitlisted",
    ]


def test_cancel_waitlisted_expires_entry() -> None:
    (svc, regs, _n, activity, _owner, student, _first, second) = (
        _full_activity_setup()
    )
    svc.cancel(activity.id, second.registration_id, student)
    assert regs.get(second.registration_id).status == "cancelled"
    assert regs.list_waitlist(activity.id, "waiting") == []


def test_review_waitlisted_approval_marks_promoted() -> None:
    (svc, regs, _n, activity, owner, _st, _first, second) = (
        _full_activity_setup()
    )
    svc.review(activity.id, second.registration_id, owner,
               "approved", None)
    assert regs.list_waitlist(activity.id, "waiting") == []
    assert regs.waitlist[0].status == "promoted"


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


def test_checkin_checkout_publish_live_events() -> None:
    """Committed mutations fan out once on attendance:{activity_id}."""
    (svc, _a, regs, att, activities, orgs, access, users, notes,
     _org, activity, owner, student) = _setup()
    events = FakeAttendanceEvents()
    att_svc = AttendanceService(
        registrations=regs, attendance=att, activities=activities,
        orgs=orgs, users=users, access=access, notifications=notes,
        events=events,
    )
    row = svc.apply(activity.id, student, None)
    svc.review(activity.id, row.registration_id, owner, "approved", None)
    record = att_svc.check_in(activity.id, row.checkin_token, owner)
    assert events.sent == [
        (activity.id, "checked_in", record.record_id, student, owner)
    ]
    att_svc.check_out(activity.id, record.record_id, owner, 2.0)
    assert events.sent[-1] == (
        activity.id, "checked_out", record.record_id, student, owner
    )


def test_failed_mutations_publish_nothing() -> None:
    """Rejected check-in/out must never emit a live event."""
    (svc, _a, regs, att, activities, orgs, access, users, notes,
     _org, activity, owner, student) = _setup()
    events = FakeAttendanceEvents()
    att_svc = AttendanceService(
        registrations=regs, attendance=att, activities=activities,
        orgs=orgs, users=users, access=access, notifications=notes,
        events=events,
    )
    row = svc.apply(activity.id, student, None)
    with pytest.raises(InvalidRegistrationStateError):
        att_svc.check_in(activity.id, row.checkin_token, owner)
    svc.review(activity.id, row.registration_id, owner, "approved", None)
    record = att_svc.check_in_manual(activity.id, row.registration_id, owner)
    att_svc.check_out(activity.id, record.record_id, owner, None)
    with pytest.raises(AlreadyCheckedInError):
        att_svc.check_in(activity.id, row.checkin_token, owner)
    with pytest.raises(InvalidRegistrationStateError):
        att_svc.check_out(activity.id, record.record_id, owner, None)
    assert [e[1] for e in events.sent] == ["checked_in", "checked_out"]
