"""SessionService unit tests: session lifecycle and QR scans."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import uuid_utils

from core.exceptions import (
    AlreadyCheckedInError,
    ForbiddenError,
    InvalidRegistrationStateError,
    NotFoundError,
)
from registrations.session_service import SessionService
from tests.unit.edge_fakes import FakeSchedules, FakeSlots
from tests.unit.member_fakes import FakeAccess, FakeUsers
from tests.unit.org_fakes import FakeOrgs
from tests.unit.registration_fakes import (
    FakeActivities,
    FakeAttendance,
    FakeAttendanceEvents,
    FakeNotifications,
    FakeRegistrations,
    published_activity,
)
from tests.unit.session_fakes import (
    FakeQrs,
    FakeScanLogs,
    FakeSessions,
    FakeSummaries,
)


def _svc():
    activities = FakeActivities()
    schedules = FakeSchedules()
    slots = FakeSlots(schedules)
    orgs = FakeOrgs()
    access = FakeAccess()
    regs = FakeRegistrations()
    att = FakeAttendance()
    sessions = FakeSessions()
    qrs = FakeQrs()
    scanlogs = FakeScanLogs()
    summaries = FakeSummaries()
    events = FakeAttendanceEvents()
    service = SessionService(
        registrations=regs,
        attendance=att,
        activities=activities,
        orgs=orgs,
        users=FakeUsers(),
        access=access,
        notifications=FakeNotifications(),
        slots=slots,
        events=events,
        sessions=sessions,
        qrcodes=qrs,
        scanlogs=scanlogs,
        schedules=schedules,
        summaries=summaries,
    )
    return (
        service, activities, schedules, orgs, regs, att,
        sessions, qrs, scanlogs, events, summaries,
    )


def _org_and_activity(orgs: FakeOrgs, activities: FakeActivities):
    owner = uuid_utils.uuid7()
    org = orgs.create(
        uuid_utils.uuid7(), owner, "Club", "club", "", "club",
        "open", None, None, None, None, "none", datetime.now(UTC),
    )
    return owner, org, published_activity(activities, org.id, owner)


def _schedule(schedules: FakeSchedules, activity_id):
    return schedules.create(
        uuid_utils.uuid7(), activity_id, "Day 1", None, None, None,
        datetime.now(UTC),
    )


def test_manager_creates_session_with_qr():
    (svc, activities, schedules, orgs, _r, _a,
     sessions, qrs, _l, _e, _m) = _svc()
    owner, org, a = _org_and_activity(orgs, activities)
    sch = _schedule(schedules, a.id)
    session = svc.create_session(
        a.id, sch.id, owner, "Check-in s\xe1ng", None, None, None
    )
    assert session.status == "scheduled"
    qr = qrs.get(session.qr_code)
    assert qr is not None and qr.status == "active"
    rows = svc.list_sessions(a.id, owner)
    assert [r.session_id for r in rows] == [session.session_id]
    with pytest.raises(ForbiddenError):
        svc.create_session(
            a.id, sch.id, uuid_utils.uuid7(), "X", None, None, None
        )


def test_session_transitions_and_code_disable():
    (svc, activities, schedules, orgs, _r, _a,
     _s, qrs, _l, _e, _m) = _svc()
    owner, org, a = _org_and_activity(orgs, activities)
    sch = _schedule(schedules, a.id)
    session = svc.create_session(
        a.id, sch.id, owner, "Ca s\xe1ng", None, None, None
    )
    with pytest.raises(InvalidRegistrationStateError):
        svc.set_status(
            a.id, sch.id, session.session_id, owner, "closed"
        )
    opened = svc.set_status(
        a.id, sch.id, session.session_id, owner, "open"
    )
    assert opened.status == "open"
    closed = svc.set_status(
        a.id, sch.id, session.session_id, owner, "closed"
    )
    assert closed.status == "closed"
    assert qrs.get(session.qr_code).status == "disabled"


def _approved(regs: FakeRegistrations, activity_id, student_id):
    row = regs.create(
        activity_id, student_id, None, uuid_utils.uuid7(),
        datetime.now(UTC), status="approved",
    )
    return row


def test_scan_accepted_marks_attended_and_logs():
    (svc, activities, schedules, orgs, regs, att,
     _s, qrs, logs, events, _m) = _svc()
    owner, org, a = _org_and_activity(orgs, activities)
    sch = _schedule(schedules, a.id)
    session = svc.create_session(
        a.id, sch.id, owner, "Ca s\xe1ng", None, None, None
    )
    svc.set_status(a.id, sch.id, session.session_id, owner, "open")
    student = uuid_utils.uuid7()
    reg = _approved(regs, a.id, student)
    record = svc.scan(session.qr_code, student, "device-1")
    assert record.session_id == session.session_id
    assert record.method == "qr"
    assert qrs.get(session.qr_code).used_count == 1
    assert regs.rows[reg.registration_id].status == "attended"
    assert logs.rows[-1].result == "accepted"
    assert events.sent[-1][1] == "checked_in"
    with pytest.raises(AlreadyCheckedInError):
        svc.scan(session.qr_code, student, "device-1")
    assert logs.rows[-1].result == "duplicate"


def test_scan_rejects_invalid_expired_and_unknown_student():
    (svc, activities, schedules, orgs, regs, _a,
     _s, qrs, logs, _e, _m) = _svc()
    owner, org, a = _org_and_activity(orgs, activities)
    sch = _schedule(schedules, a.id)
    session = svc.create_session(
        a.id, sch.id, owner, "Ca s\xe1ng", None, None, None
    )
    student = uuid_utils.uuid7()
    with pytest.raises(NotFoundError):
        svc.scan("not-a-code", student, None)
    assert logs.rows[-1].result == "invalid"
    # Session still scheduled -> invalid, not expired.
    with pytest.raises(InvalidRegistrationStateError):
        svc.scan(session.qr_code, student, None)
    assert logs.rows[-1].result == "invalid"
    svc.set_status(a.id, sch.id, session.session_id, owner, "open")
    # Student without registration -> invalid.
    with pytest.raises(InvalidRegistrationStateError):
        svc.scan(session.qr_code, student, None)
    assert logs.rows[-1].result == "invalid"
    # Disabled code -> expired.
    svc.set_status(a.id, sch.id, session.session_id, owner, "closed")
    _approved(regs, a.id, student)
    with pytest.raises(InvalidRegistrationStateError):
        svc.scan(session.qr_code, student, None)
    assert logs.rows[-1].result == "expired"


def test_scan_prefers_registration_on_session_schedule():
    (svc, activities, schedules, orgs, regs, att,
     _s, _q, _l, _e, _m) = _svc()
    owner, org, a = _org_and_activity(orgs, activities)
    sch = _schedule(schedules, a.id)
    other = _schedule(schedules, a.id)
    slot = svc._slots.create(
        uuid_utils.uuid7(), sch.id, "Morning", 5, None, None
    )
    student = uuid_utils.uuid7()
    wrong = regs.create(
        a.id, student, None, uuid_utils.uuid7(), datetime.now(UTC),
        status="approved",
    )
    right = regs.create(
        a.id, student, None, uuid_utils.uuid7(), datetime.now(UTC),
        status="approved", slot_id=slot.slot_id,
    )
    session = svc.create_session(
        a.id, sch.id, owner, "Ca s\xe1ng", None, None, None
    )
    svc.set_status(a.id, sch.id, session.session_id, owner, "open")
    record = svc.scan(session.qr_code, student, None)
    assert record is not None
    assert regs.rows[right.registration_id].status == "attended"
    assert regs.rows[wrong.registration_id].status == "approved"
