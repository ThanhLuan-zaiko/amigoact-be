"""Attendance business rules: check-in/out around approved registrations."""

from __future__ import annotations

from uuid import UUID

from core.exceptions import (
    InvalidRegistrationStateError,
    NotFoundError,
)
from core.security import utcnow
from registrations.model import AttendanceRecord
from registrations.service import _RegistrationBase


class AttendanceService(_RegistrationBase):
    """Staff-driven check-in/out; shares deps with RegistrationService."""

    def check_in(
        self,
        activity_id: UUID,
        checkin_token: UUID,
        staff_id: UUID,
        method: str = "qr",
    ) -> AttendanceRecord:
        """Staff scans the personal token; one record per registration."""
        activity = self._activity(activity_id)
        self._require_manager(
            activity.org_id, staff_id, "attendance.checkin"
        )
        index = self._registrations.get_by_token(checkin_token)
        if index is None or index.activity_id != activity_id:
            raise NotFoundError("Check-in token is invalid.")
        row = self._registrations.get(index.registration_id)
        if row is None:
            raise NotFoundError("Registration not found.")
        if row.status not in {"approved", "attended"}:
            raise InvalidRegistrationStateError(
                "Only approved registrations can check in."
            )
        now = utcnow()
        record = self._attendance.create(
            row.registration_id, activity_id, row.student_id,
            None, method, staff_id, now,
        )
        if row.status == "approved":
            self._registrations.set_status(
                row.registration_id, "attended", staff_id, None, now
            )
            self._registrations.record_history(
                row.registration_id, "approved", "attended",
                staff_id, f"check-in via {method}", now,
            )
        self._access.record(
            activity.org_id, staff_id, "attendance.checkin",
            "registration", row.registration_id, "allowed",
        )
        return record

    def check_in_manual(
        self,
        activity_id: UUID,
        registration_id: UUID,
        staff_id: UUID,
    ) -> AttendanceRecord:
        """Manager check-in straight from the roster (no QR needed)."""
        row = self._registrations.get(registration_id)
        if row is None or row.activity_id != activity_id:
            raise NotFoundError("Registration not found.")
        return self.check_in(
            activity_id, row.checkin_token, staff_id, "manual"
        )

    def check_out(
        self,
        activity_id: UUID,
        record_id: UUID,
        staff_id: UUID,
        actual_hours: float | None,
    ) -> AttendanceRecord:
        """Stamp check-out; hours default from in/out duration."""
        activity = self._activity(activity_id)
        self._require_manager(
            activity.org_id, staff_id, "attendance.checkout"
        )
        record = self._attendance.get(record_id)
        if record is None or record.activity_id != activity_id:
            raise NotFoundError("Attendance record not found.")
        if record.checked_out_at is not None:
            raise InvalidRegistrationStateError("Already checked out.")
        now = utcnow()
        hours = actual_hours
        if hours is None and record.scanned_at is not None:
            delta = now - record.scanned_at
            hours = round(max(delta.total_seconds() / 3600.0, 0.0), 2)
        updated = self._attendance.check_out(
            record_id, "manual", hours, now
        )
        assert updated is not None
        if self._hours is not None:
            guard = self._registrations.get_for_student(
                activity_id, record.student_id, UUID(int=0)
            )
            credited = (
                updated.actual_hours
                if updated.actual_hours is not None
                else getattr(activity, "hours_awarded", 0.0) or 0.0
            )
            if credited > 0:
                self._hours.record_attendance(
                    activity.org_id, activity_id, record.student_id,
                    guard.registration_id if guard is not None else None,
                    credited, staff_id,
                )
        return updated

    def list_attendance(
        self, activity_id: UUID, viewer_id: UUID
    ) -> list[AttendanceRecord]:
        """Manager feed of every check-in on one activity."""
        activity = self._activity(activity_id)
        self._require_manager(
            activity.org_id, viewer_id, "attendance.list"
        )
        return self._attendance.list_by_activity(activity_id)

    def my_attendance(
        self, student_id: UUID
    ) -> list[AttendanceRecord]:
        """One student's check-in history across activities."""
        return self._attendance.list_by_student(student_id)
