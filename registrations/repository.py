"""cqlengine persistence for registration + attendance projections.

The (activity, student, slot) uniqueness claim uses raw CQL LWT because
cqlengine cannot surface `[applied]` from an ORM create - same
justification as org slug claims.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from cassandra.cqlengine.connection import get_session

from core.exceptions import AlreadyRegisteredError
from registrations.interfaces import RegistrationStore
from registrations.model import (
    Registration,
    RegistrationStatusHistory,
    RegistrationsByActivity,
    RegistrationsByActivityStudent,
    RegistrationsByStudent,
    RegistrationsByToken,
)


def _sync_feeds(row: Registration) -> None:
    """Mirror the canonical row's status across every query table."""
    slot = row.slot_id
    RegistrationsByActivity.objects(
        activity_id=row.activity_id,
        registered_at=row.registered_at,
        registration_id=row.registration_id,
    ).update(
        student_id=row.student_id, slot_id=slot, status=row.status
    )
    RegistrationsByStudent.objects(
        student_id=row.student_id,
        registered_at=row.registered_at,
        registration_id=row.registration_id,
    ).update(activity_id=row.activity_id, status=row.status)
    RegistrationsByActivityStudent.objects(
        activity_id=row.activity_id,
        student_id=row.student_id,
        slot_id=slot,
    ).update(status=row.status)
    RegistrationsByToken.objects(
        checkin_token=row.checkin_token
    ).update(status=row.status)


def _write_token_index(row: Registration) -> None:
    """Insert the token lookup row carrying its FK columns once."""
    RegistrationsByToken.objects(
        checkin_token=row.checkin_token
    ).update(
        registration_id=row.registration_id,
        activity_id=row.activity_id,
        student_id=row.student_id,
        slot_id=row.slot_id,
        status=row.status,
    )


class CqlRegistrationStore(RegistrationStore):
    """Registration aggregate plus all four denormalized feeds."""

    def __init__(self, keyspace: str) -> None:
        self._keyspace = keyspace

    def create(
        self,
        activity_id: UUID,
        student_id: UUID,
        note: str | None,
        checkin_token: UUID,
        now: datetime,
    ) -> Registration:
        """Claim the (activity, student, zero-slot) row, then fan out."""
        from core.ids import uuid7

        registration_id = uuid7()
        claim = get_session().execute(
            f"INSERT INTO {self._keyspace}.registrations_by_activity_student"
            " (activity_id, student_id, slot_id, registration_id, status,"
            " registered_at)"
            " VALUES (%s, %s, %s, %s, %s, %s) IF NOT EXISTS",
            [
                activity_id,
                student_id,
                UUID(int=0),
                registration_id,
                "pending",
                now,
            ],
        )
        if not claim.was_applied:
            raise AlreadyRegisteredError(
                "You already registered for this activity."
            )
        row = Registration.create(
            registration_id=registration_id,
            activity_id=activity_id,
            student_id=student_id,
            slot_id=UUID(int=0),
            status="pending",
            note=note,
            checkin_token=checkin_token,
            registered_at=now,
        )
        _write_token_index(row)
        _sync_feeds(row)
        return row

    def reapply(
        self,
        registration_id: UUID,
        activity_id: UUID,
        student_id: UUID,
        note: str | None,
        checkin_token: UUID,
        now: datetime,
    ) -> Registration:
        """Flip a terminal guard row back to pending under a new id."""
        RegistrationsByActivityStudent.objects(
            activity_id=activity_id,
            student_id=student_id,
            slot_id=UUID(int=0),
        ).update(
            registration_id=registration_id,
            status="pending",
            registered_at=now,
        )
        row = Registration.create(
            registration_id=registration_id,
            activity_id=activity_id,
            student_id=student_id,
            slot_id=UUID(int=0),
            status="pending",
            note=note,
            checkin_token=checkin_token,
            registered_at=now,
        )
        _write_token_index(row)
        _sync_feeds(row)
        return row

    def get(self, registration_id: UUID) -> Registration | None:
        try:
            return Registration.get(registration_id=registration_id)
        except Registration.DoesNotExist:
            return None

    def get_for_student(
        self, activity_id: UUID, student_id: UUID, slot_id: UUID
    ) -> RegistrationsByActivityStudent | None:
        try:
            return RegistrationsByActivityStudent.get(
                activity_id=activity_id,
                student_id=student_id,
                slot_id=slot_id,
            )
        except RegistrationsByActivityStudent.DoesNotExist:
            return None

    def get_by_token(
        self, checkin_token: UUID
    ) -> RegistrationsByToken | None:
        try:
            return RegistrationsByToken.get(checkin_token=checkin_token)
        except RegistrationsByToken.DoesNotExist:
            return None

    def set_status(
        self,
        registration_id: UUID,
        status: str,
        reviewer_id: UUID | None,
        review_note: str | None,
        now: datetime,
    ) -> Registration | None:
        row = self.get(registration_id)
        if row is None:
            return None
        updates: dict = {"status": status}
        if reviewer_id is not None:
            updates["reviewed_by"] = reviewer_id
            updates["reviewed_at"] = now
        if review_note is not None:
            updates["review_note"] = review_note
        if status == "cancelled":
            updates["cancelled_at"] = now
        Registration.objects(registration_id=registration_id).update(
            **updates
        )
        row = self.get(registration_id)
        if row is not None:
            _sync_feeds(row)
        return row

    def list_by_activity(
        self, activity_id: UUID, limit: int = 200
    ) -> list[Registration]:
        rows = list(
            RegistrationsByActivity.objects(activity_id=activity_id)
            .limit(limit)
        )
        return [
            row
            for r in rows
            if (row := self.get(r.registration_id)) is not None
        ]

    def list_by_student(
        self, student_id: UUID, limit: int = 100
    ) -> list[Registration]:
        rows = list(
            RegistrationsByStudent.objects(student_id=student_id).limit(
                limit
            )
        )
        return [
            row
            for r in rows
            if (row := self.get(r.registration_id)) is not None
        ]

    def record_history(
        self,
        registration_id: UUID,
        from_status: str | None,
        to_status: str,
        changed_by: UUID,
        note: str | None,
        now: datetime,
    ) -> None:
        RegistrationStatusHistory.create(
            registration_id=registration_id,
            changed_at=now,
            from_status=from_status,
            to_status=to_status,
            changed_by=changed_by,
            note=note,
        )
