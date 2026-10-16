"""Read-side queries for the registrations aggregate (roster, history)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from core.exceptions import ForbiddenError, NotFoundError
from registrations.model import Registration, RegistrationStatusHistory


@dataclass
class RosterItem:
    """Manager view of one application with student contact."""

    registration_id: UUID
    student_id: UUID
    student_name: str
    student_email: str | None
    status: str
    note: str | None
    review_note: str | None
    registered_at: object
    form_data: dict | None = None
    slot_id: UUID | None = None


class RegistrationQueriesMixin:
    """List/detail reads shared by the registration service."""

    def list_for_activity(
        self, activity_id: UUID, viewer_id: UUID
    ) -> list[RosterItem]:
        """Manager roster with the applicant's name and email attached."""
        activity = self._activity(activity_id)
        self._require_manager(
            activity.org_id, viewer_id, "registration.list"
        )
        rows = self._registrations.list_by_activity(activity_id)
        return [
            RosterItem(
                registration_id=row.registration_id,
                student_id=row.student_id,
                student_name=(
                    brief.full_name
                    if (brief := self._users.get_brief(row.student_id))
                    else "Ng\u01b0\u1eddi d\xf9ng"
                ),
                student_email=brief.email if brief else None,
                status=row.status,
                note=row.note,
                review_note=row.review_note,
                registered_at=row.registered_at,
                form_data=(
                    json.loads(row.form_data)
                    if getattr(row, "form_data", None)
                    else None
                ),
                slot_id=(
                    None
                    if row.slot_id == UUID(int=0)
                    else row.slot_id
                ),
            )
            for row in rows
        ]

    def list_mine(self, student_id: UUID) -> list[Registration]:
        """Applicant's own history, newest first."""
        return self._registrations.list_by_student(student_id)

    def history(
        self, activity_id: UUID, registration_id: UUID, viewer_id: UUID
    ) -> list[RegistrationStatusHistory]:
        """Audit feed visible to the applicant and org managers."""
        activity = self._activity(activity_id)
        row = self._registrations.get(registration_id)
        if row is None or row.activity_id != activity_id:
            raise NotFoundError("Registration not found.")
        if row.student_id != viewer_id:
            self._require_manager(
                activity.org_id, viewer_id, "registration.history"
            )
        return self._registrations.list_history(registration_id)

    def my_ticket(
        self, activity_id: UUID, registration_id: UUID, user_id: UUID
    ) -> Registration:
        """QR payload only resolves for the applicant themselves."""
        row = self._registrations.get(registration_id)
        if row is None or row.activity_id != activity_id:
            raise NotFoundError("Registration not found.")
        if row.student_id != user_id:
            raise ForbiddenError("Only the applicant can view this ticket.")
        return row
