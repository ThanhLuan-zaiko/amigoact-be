"""One best registration per activity for one student (the 'my status' chip).

A student who attended beats a cancelled earlier try. Ties go to the
newest registration. Only this rule decides which row represents an
activity, so every reader agrees on the same status.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from registrations.interfaces import RegistrationBriefStore

# Lower rank wins.
STATUS_RANK = {
    "attended": 0,
    "approved": 1,
    "pending": 2,
    "waitlisted": 3,
    "rejected": 4,
    "cancelled": 5,
}
_EPOCH = datetime(1970, 1, 1)


@dataclass(frozen=True)
class StudentBrief:
    activity_id: UUID
    registration_id: UUID
    status: str
    registered_at: datetime | None


def _seconds(moment: datetime | None) -> float:
    return ((moment or _EPOCH) - _EPOCH).total_seconds()


def _beats(candidate: StudentBrief, current: StudentBrief) -> bool:
    """Lower rank first, then the newest registration."""
    challenger = (
        STATUS_RANK.get(candidate.status, len(STATUS_RANK)),
        -_seconds(candidate.registered_at),
    )
    incumbent = (
        STATUS_RANK.get(current.status, len(STATUS_RANK)),
        -_seconds(current.registered_at),
    )
    return challenger < incumbent


class RegistrationBriefService:
    """Collapses a student's history into one brief per activity."""

    def __init__(self, store: RegistrationBriefStore) -> None:
        self._store = store

    def briefs_for(self, student_id: UUID) -> list[StudentBrief]:
        best: dict[UUID, StudentBrief] = {}
        for row in self._store.student_rows(student_id):
            brief = StudentBrief(
                activity_id=row.activity_id,
                registration_id=row.registration_id,
                status=row.status,
                registered_at=row.registered_at,
            )
            current = best.get(brief.activity_id)
            if current is None or _beats(brief, current):
                best[brief.activity_id] = brief
        return list(best.values())
