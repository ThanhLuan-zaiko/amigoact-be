"""cqlengine persistence for attendance records and their feeds.

The per-registration claim uses raw CQL LWT because cqlengine cannot
surface `[applied]` from an ORM create (same justification as slugs).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from cassandra.cqlengine.connection import get_session

from core.exceptions import AlreadyCheckedInError
from registrations.interfaces import AttendanceStore
from registrations.model import (
    AttendanceByActivity,
    AttendanceByRegistration,
    AttendanceByStudent,
    AttendanceRecord,
)


class CqlAttendanceStore(AttendanceStore):
    """Check-in/out writes plus the three read feeds."""

    def __init__(self, keyspace: str) -> None:
        self._keyspace = keyspace

    def create(
        self,
        registration_id: UUID,
        activity_id: UUID,
        student_id: UUID,
        session_id: UUID | None,
        method: str,
        verified_by: UUID | None,
        now: datetime,
    ) -> AttendanceRecord:
        """Claim the registration slot with LWT, then write all feeds."""
        from core.ids import uuid7

        record_id = uuid7()
        claim = get_session().execute(
            f"INSERT INTO {self._keyspace}.attendance_by_registration"
            " (registration_id, record_id, activity_id, student_id,"
            " session_id, scanned_at)"
            " VALUES (%s, %s, %s, %s, %s, %s) IF NOT EXISTS",
            [registration_id, record_id, activity_id, student_id,
             session_id, now],
        )
        if not claim.was_applied:
            raise AlreadyCheckedInError(
                "This registration was already checked in."
            )
        record = AttendanceRecord.create(
            record_id=record_id,
            activity_id=activity_id,
            student_id=student_id,
            session_id=session_id,
            method=method,
            verified_by=verified_by,
            scanned_at=now,
        )
        AttendanceByActivity.create(
            activity_id=activity_id,
            scanned_at=now,
            record_id=record.record_id,
            student_id=student_id,
            session_id=session_id,
            method=method,
        )
        AttendanceByStudent.create(
            student_id=student_id,
            scanned_at=now,
            record_id=record.record_id,
            activity_id=activity_id,
            session_id=session_id,
            method=method,
        )
        return record

    def get_for_registration(
        self, registration_id: UUID
    ) -> AttendanceByRegistration | None:
        try:
            return AttendanceByRegistration.get(
                registration_id=registration_id
            )
        except AttendanceByRegistration.DoesNotExist:
            return None

    def get(self, record_id: UUID) -> AttendanceRecord | None:
        try:
            return AttendanceRecord.get(record_id=record_id)
        except AttendanceRecord.DoesNotExist:
            return None

    def check_out(
        self,
        record_id: UUID,
        method: str,
        actual_hours: float | None,
        now: datetime,
    ) -> AttendanceRecord | None:
        row = self.get(record_id)
        if row is None:
            return None
        AttendanceRecord.objects(record_id=record_id).update(
            checked_out_at=now,
            check_out_method=method,
            actual_hours=actual_hours,
        )
        return self.get(record_id)

    def list_by_activity(
        self, activity_id: UUID, limit: int = 200
    ) -> list[AttendanceRecord]:
        rows = list(
            AttendanceByActivity.objects(activity_id=activity_id).limit(
                limit
            )
        )
        return [
            row
            for r in rows
            if (row := self.get(r.record_id)) is not None
        ]

    def list_by_student(
        self, student_id: UUID, limit: int = 100
    ) -> list[AttendanceRecord]:
        rows = list(
            AttendanceByStudent.objects(student_id=student_id).limit(
                limit
            )
        )
        return [
            row
            for r in rows
            if (row := self.get(r.record_id)) is not None
        ]
