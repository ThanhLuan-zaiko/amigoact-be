"""Shared in-memory ports for registration/attendance unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import uuid_utils

from registrations.attendance_service import AttendanceService
from registrations.interfaces import (
    AttendanceEvents,
    AttendanceStore,
    RegistrationStore,
)
from registrations.service import RegistrationService
from tests.unit.activity_fakes import FakeActivities
from tests.unit.member_fakes import FakeAccess, FakeUsers
from tests.unit.org_fakes import FakeOrgs


class FakeRegistrations(RegistrationStore):
    def __init__(self) -> None:
        self.rows: dict[UUID, Any] = {}
        self.guards: dict[tuple, Any] = {}
        self.tokens: dict[UUID, Any] = {}
        self.history: list[tuple] = []

    def create(self, activity_id, student_id, note, checkin_token, now):  # noqa: ANN001, ANN202
        from core.exceptions import AlreadyRegisteredError

        key = (activity_id, student_id, UUID(int=0))
        if key in self.guards:
            raise AlreadyRegisteredError("dup")
        row = SimpleNamespace(
            registration_id=uuid_utils.uuid7(),
            activity_id=activity_id, student_id=student_id,
            slot_id=UUID(int=0), status="pending", note=note,
            review_note=None, reviewed_by=None, reviewed_at=None,
            checkin_token=checkin_token, registered_at=now,
            cancelled_at=None, form_data=None,
        )
        self.rows[row.registration_id] = row
        self.guards[key] = row
        self.tokens[checkin_token] = row
        return row

    def reapply(self, registration_id, activity_id, student_id, note, checkin_token, now):  # noqa: ANN001, ANN202
        key = (activity_id, student_id, UUID(int=0))
        row = SimpleNamespace(
            registration_id=registration_id,
            activity_id=activity_id, student_id=student_id,
            slot_id=UUID(int=0), status="pending", note=note,
            review_note=None, reviewed_by=None, reviewed_at=None,
            checkin_token=checkin_token, registered_at=now,
            cancelled_at=None, form_data=None,
        )
        self.rows[registration_id] = row
        self.guards[key] = row
        self.tokens[checkin_token] = row
        return row

    def get(self, registration_id):  # noqa: ANN001, ANN202
        return self.rows.get(registration_id)

    def get_for_student(self, activity_id, student_id, slot_id):  # noqa: ANN001, ANN202
        return self.guards.get((activity_id, student_id, slot_id))

    def get_by_token(self, checkin_token):  # noqa: ANN001, ANN202
        return self.tokens.get(checkin_token)

    def set_status(self, registration_id, status, reviewer_id, review_note, now):  # noqa: ANN001, ANN202
        row = self.rows.get(registration_id)
        if row is None:
            return None
        row.status = status
        if reviewer_id is not None:
            row.reviewed_by = reviewer_id
            row.reviewed_at = now
        if review_note is not None:
            row.review_note = review_note
        if status == "cancelled":
            row.cancelled_at = now
        return row

    def list_by_activity(self, activity_id, limit=200):  # noqa: ANN001, ANN202
        return [
            r for r in self.rows.values() if r.activity_id == activity_id
        ][:limit]

    def list_by_student(self, student_id, limit=100):  # noqa: ANN001, ANN202
        return [
            r for r in self.rows.values() if r.student_id == student_id
        ][:limit]

    def record_history(self, registration_id, from_status, to_status, changed_by, note, now):  # noqa: ANN001, ANN202
        self.history.append((registration_id, from_status, to_status))


class FakeAttendance(AttendanceStore):
    def __init__(self) -> None:
        self.rows: dict[UUID, Any] = {}
        self.by_registration: dict[UUID, Any] = {}

    def create(self, registration_id, activity_id, student_id, session_id, method, verified_by, now):  # noqa: ANN001, ANN202
        from core.exceptions import AlreadyCheckedInError

        if registration_id in self.by_registration:
            raise AlreadyCheckedInError("dup")
        row = SimpleNamespace(
            record_id=uuid_utils.uuid7(),
            registration_id=registration_id,
            activity_id=activity_id, student_id=student_id,
            session_id=session_id, method=method,
            scanned_at=now, verified_by=verified_by,
            checked_out_at=None, check_out_method=None,
            actual_hours=None,
        )
        self.rows[row.record_id] = row
        self.by_registration[registration_id] = row
        return row

    def get_for_registration(self, registration_id):  # noqa: ANN001, ANN202
        return self.by_registration.get(registration_id)

    def get(self, record_id):  # noqa: ANN001, ANN202
        return self.rows.get(record_id)

    def check_out(self, record_id, method, actual_hours, now):  # noqa: ANN001, ANN202
        row = self.rows.get(record_id)
        if row is None:
            return None
        row.checked_out_at = now
        row.check_out_method = method
        row.actual_hours = actual_hours
        return row

    def list_by_activity(self, activity_id, limit=200):  # noqa: ANN001, ANN202
        return [
            r for r in self.rows.values() if r.activity_id == activity_id
        ][:limit]

    def list_by_student(self, student_id, limit=100):  # noqa: ANN001, ANN202
        return [
            r for r in self.rows.values() if r.student_id == student_id
        ][:limit]


class FakeNotifications:
    def __init__(self) -> None:
        self.sent: list[tuple] = []

    def notify(self, user_id, type, title, body="", data_json=None):  # noqa: ANN001, ANN202, A002
        self.sent.append((user_id, type, title))


class FakeAttendanceEvents(AttendanceEvents):
    """Captures live attendance events instead of publishing them."""

    def __init__(self) -> None:
        self.sent: list[tuple] = []

    def attendance_changed(self, activity_id, action, record_id, student_id, actor_id):  # noqa: ANN001, ANN202
        self.sent.append(
            (activity_id, action, record_id, student_id, actor_id)
        )


def make_reg_services() -> tuple[
    RegistrationService, AttendanceService,
    FakeRegistrations, FakeAttendance, FakeActivities,
    FakeOrgs, FakeAccess, FakeUsers, FakeNotifications,
]:
    regs = FakeRegistrations()
    att = FakeAttendance()
    activities = FakeActivities()
    orgs = FakeOrgs()
    access = FakeAccess()
    users = FakeUsers()
    notes = FakeNotifications()
    kwargs = dict(
        registrations=regs, attendance=att, activities=activities,
        orgs=orgs, users=users, access=access, notifications=notes,
    )
    return (
        RegistrationService(**kwargs), AttendanceService(**kwargs),
        regs, att, activities, orgs, access, users, notes,
    )


def published_activity(activities: FakeActivities, org_id, owner):
    """Insert one published activity row in the fake store."""
    from types import SimpleNamespace
    from datetime import UTC, datetime, timedelta

    from tests.unit.activity_fakes import _fields

    row = activities.create(
        org_id, owner,
        _fields(None, start_at=datetime.now(UTC) + timedelta(days=7)),
        datetime.now(UTC),
    )
    row.status = "published"
    row.published_at = datetime.now(UTC)
    return row
