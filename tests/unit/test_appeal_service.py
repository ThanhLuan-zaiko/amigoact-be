"""AppealService + attendance summary unit tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import uuid_utils

from core.exceptions import (
    ForbiddenError,
    InvalidRegistrationStateError,
    NotFoundError,
)
from registrations.appeal_service import AppealService
from tests.unit.edge_fakes import FakeSchedules, FakeSlots
from tests.unit.member_fakes import FakeAccess, FakeUsers
from tests.unit.org_fakes import FakeOrgs
from tests.unit.registration_fakes import (
    FakeActivities,
    FakeAttendance,
    FakeNotifications,
    FakeRegistrations,
    published_activity,
)
from tests.unit.session_fakes import (
    FakeAppeals,
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
    appeals = FakeAppeals()
    notifications = FakeNotifications()
    service = AppealService(
        registrations=regs,
        attendance=att,
        activities=activities,
        orgs=orgs,
        users=FakeUsers(),
        access=access,
        notifications=notifications,
        appeals=appeals,
    )
    return service, activities, schedules, orgs, regs, att, appeals, notifications


def _org_and_activity(orgs: FakeOrgs, activities: FakeActivities):
    owner = uuid_utils.uuid7()
    org = orgs.create(
        uuid_utils.uuid7(), owner, "Club", "club", "", "club",
        "open", None, None, None, None, "none", datetime.now(UTC),
    )
    return owner, org, published_activity(activities, org.id, owner)


def _approved(regs: FakeRegistrations, activity_id, student_id):
    return regs.create(
        activity_id, student_id, None, uuid_utils.uuid7(),
        datetime.now(UTC), status="approved",
    )


def test_student_files_and_lists_own_appeal():
    svc, activities, _sch, orgs, regs, _att, appeals, _n = _svc()
    _owner, _org, a = _org_and_activity(orgs, activities)
    student = uuid_utils.uuid7()
    _approved(regs, a.id, student)
    appeal = svc.file(a.id, student, "T\xf4i c\xf3 qu\xe9t m\xe3 nh\u01b0ng m\xe1y l\u1ed7i")
    assert appeal.status == "pending"
    mine = svc.mine(a.id, student)
    assert [r.appeal_id for r in mine] == [appeal.appeal_id]
    # No registration -> cannot file.
    with pytest.raises(NotFoundError):
        svc.file(a.id, uuid_utils.uuid7(), "Kh\xf4ng c\xf3 \u0111\u01a1n")


def test_manager_queue_and_student_cannot_list_all():
    svc, activities, _sch, orgs, regs, _att, _ap, _n = _svc()
    owner, _org, a = _org_and_activity(orgs, activities)
    student = uuid_utils.uuid7()
    _approved(regs, a.id, student)
    svc.file(a.id, student, "Qu\xe9t nh\u1ea7m phi\xean")
    rows = svc.list_for_activity(a.id, owner)
    assert len(rows) == 1 and rows[0].status == "pending"
    with pytest.raises(ForbiddenError):
        svc.list_for_activity(a.id, student)


def test_approve_appeal_grants_attendance_and_notifies():
    svc, activities, _sch, orgs, regs, att, _ap, notifications = _svc()
    owner, _org, a = _org_and_activity(orgs, activities)
    student = uuid_utils.uuid7()
    reg = _approved(regs, a.id, student)
    appeal = svc.file(a.id, student, "BTC b\u1ecf s\xf3t")
    updated = svc.resolve(
        a.id, student, appeal.appeal_id, owner, "approved"
    )
    assert updated.status == "approved"
    assert updated.resolved_by == owner
    record = att.get_for_registration(reg.registration_id)
    assert record is not None and record.method == "manual"
    assert regs.rows[reg.registration_id].status == "attended"
    note = notifications.sent[-1]
    assert note[0] == student and note[1] == "registration"
    # Cannot resolve twice.
    with pytest.raises(InvalidRegistrationStateError):
        svc.resolve(a.id, student, appeal.appeal_id, owner, "approved")


def test_reject_appeal_marks_only():
    svc, activities, _sch, orgs, regs, att, _ap, notifications = _svc()
    owner, _org, a = _org_and_activity(orgs, activities)
    student = uuid_utils.uuid7()
    reg = _approved(regs, a.id, student)
    appeal = svc.file(a.id, student, "Nh\u1ea7m")
    updated = svc.resolve(
        a.id, student, appeal.appeal_id, owner, "rejected"
    )
    assert updated.status == "rejected"
    assert att.get_for_registration(reg.registration_id) is None
    assert notifications.sent[-1][0] == student


def test_summary_counts_sessions_and_attendance():
    from registrations.session_service import SessionService

    activities = FakeActivities()
    schedules = FakeSchedules()
    slots = FakeSlots(schedules)
    orgs = FakeOrgs()
    access = FakeAccess()
    regs = FakeRegistrations()
    att = FakeAttendance()
    sessions = FakeSessions()
    summaries = FakeSummaries()
    service = SessionService(
        registrations=regs, attendance=att, activities=activities,
        orgs=orgs, users=FakeUsers(), access=access,
        notifications=FakeNotifications(), slots=slots,
        sessions=sessions, qrcodes=FakeQrs(),
        scanlogs=FakeScanLogs(), schedules=schedules,
        summaries=summaries,
    )
    owner, _org, a = _org_and_activity(orgs, activities)
    sch = schedules.create(
        uuid_utils.uuid7(), a.id, "Day 1", None, None, None,
        datetime.now(UTC),
    )
    session = service.create_session(
        a.id, sch.id, owner, "S1", None, None, None
    )
    service.set_status(a.id, sch.id, session.session_id, owner, "open")
    student = uuid_utils.uuid7()
    reg = _approved(regs, a.id, student)
    row = service.summary(a.id, reg.registration_id, student)
    assert row.sessions_total == 1
    assert row.sessions_attended == 0
    assert row.status == "incomplete"
    # Accepted scan refreshes the rollup.
    service.scan(session.qr_code, student, None)
    row = summaries.get(reg.registration_id)
    assert row.sessions_attended == 1 and row.status == "complete"
    # Student cannot read someone else's summary.
    with pytest.raises(ForbiddenError):
        service.summary(a.id, reg.registration_id, uuid_utils.uuid7())
