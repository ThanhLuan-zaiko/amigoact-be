"""cqlengine read for one student's registration rows (a single partition)."""

from __future__ import annotations

from uuid import UUID

from registrations.interfaces import RegistrationBriefStore
from registrations.model import RegistrationsByStudent


class CqlRegistrationBriefStore(RegistrationBriefStore):
    """Reads the by-student feed, whose status _sync_feeds keeps current."""

    def student_rows(
        self, student_id: UUID, limit: int = 500
    ) -> list[RegistrationsByStudent]:
        return list(
            RegistrationsByStudent.objects(student_id=student_id).limit(limit)
        )
