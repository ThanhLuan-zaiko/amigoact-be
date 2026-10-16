"""Attendance appeals: students dispute, managers resolve."""

from __future__ import annotations

from uuid import UUID

from core.exceptions import (
    InvalidRegistrationStateError,
    NotFoundError,
)
from core.ids import uuid7
from core.security import utcnow
from registrations.model import AttendanceAppeal
from registrations.service import _RegistrationBase
from registrations.session_interfaces import AppealStore

APPEAL_RESOLUTIONS = {"approved", "rejected"}


class AppealService(_RegistrationBase):
    """Appeal queue scoped to one activity."""

    def __init__(self, *args, appeals: AppealStore, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._appeals = appeals

    def _student_registration(self, activity_id: UUID, student_id: UUID):
        """Any live registration the student holds on the activity."""
        return next(
            (
                r
                for r in self._registrations.list_by_student(student_id)
                if r.activity_id == activity_id
                and r.status not in ("cancelled", "rejected")
            ),
            None,
        )

    def file(
        self,
        activity_id: UUID,
        student_id: UUID,
        reason: str,
        record_id: UUID | None = None,
    ) -> AttendanceAppeal:
        """Students appeal a missing/wrong attendance record."""
        self._activity(activity_id)
        if self._student_registration(activity_id, student_id) is None:
            raise NotFoundError(
                "You have no registration for this activity."
            )
        return self._appeals.create(
            activity_id, student_id, uuid7(), record_id,
            reason.strip(), utcnow(),
        )

    def list_for_activity(
        self, activity_id: UUID, viewer_id: UUID
    ) -> list[AttendanceAppeal]:
        """Manager queue of appeals, pending first."""
        activity = self._activity(activity_id)
        self._require_manager(
            activity.org_id, viewer_id, "attendance.appeal"
        )
        rows = self._appeals.list_by_activity(activity_id)
        return sorted(
            rows, key=lambda r: (r.status != "pending", r.created_at)
        )

    def mine(
        self, activity_id: UUID, student_id: UUID
    ) -> list[AttendanceAppeal]:
        """The caller's own appeals for one activity."""
        self._activity(activity_id)
        return self._appeals.list_for_student(activity_id, student_id)

    def resolve(
        self,
        activity_id: UUID,
        student_id: UUID,
        appeal_id: UUID,
        resolver_id: UUID,
        target: str,
    ) -> AttendanceAppeal:
        """Approve grants a manual check-in; reject just stamps it."""
        activity = self._activity(activity_id)
        self._require_manager(
            activity.org_id, resolver_id, "attendance.appeal"
        )
        if target not in APPEAL_RESOLUTIONS:
            raise InvalidRegistrationStateError(
                "Appeal resolution must be approved or rejected."
            )
        appeal = self._appeals.get(activity_id, student_id, appeal_id)
        if appeal is None:
            raise NotFoundError("Appeal not found.")
        if appeal.status != "pending":
            raise InvalidRegistrationStateError(
                "Appeal was already resolved."
            )
        now = utcnow()
        updated = self._appeals.resolve(
            activity_id, student_id, appeal_id,
            target, resolver_id, now,
        )
        assert updated is not None
        if target == "approved":
            registration = self._student_registration(
                activity_id, student_id
            )
            if (
                registration is not None
                and self._attendance.get_for_registration(
                    registration.registration_id
                ) is None
            ):
                self._attendance.create(
                    registration.registration_id, activity_id,
                    student_id, None, "manual", resolver_id, now,
                )
                if registration.status == "approved":
                    self._registrations.set_status(
                        registration.registration_id, "attended",
                        resolver_id, None, now,
                    )
                    self._registrations.record_history(
                        registration.registration_id, "approved",
                        "attended", resolver_id,
                        "attendance appeal approved", now,
                    )
        self._notify(
            student_id,
            "Khi\u1ebfu n\u1ea1i \u0111i\u1ec3m danh",
            f"Khi\u1ebfu n\u1ea1i c\u1ee7a b\u1ea1n \u1edf {activity.title} \u0111\xe3 \u0111\u01b0\u1ee3c "
            f"{'ch\u1ea5p nh\u1eadn' if target == 'approved' else 't\u1eeb ch\u1ed1i'}.",
            {
                "activity_id": str(activity_id),
                "appeal_id": str(appeal_id),
                "status": target,
            },
        )
        return updated
