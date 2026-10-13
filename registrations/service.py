"""Registration and attendance business rules (no FastAPI, no CQL)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from activities.interfaces import ActivityStore
from core.exceptions import (
    ForbiddenError,
    InvalidRegistrationStateError,
    NotFoundError,
    RegistrationClosedError,
)
from core.ids import uuid7
from core.security import utcnow
from hours.interfaces import HourRecorder
from notifications.interfaces import NotificationPort
from orgs.interfaces import OrgRepository, UserDirectory
from rbac.interfaces import AccessControl
from registrations.interfaces import (
    AttendanceEvents,
    AttendanceStore,
    RegistrationStore,
)
from registrations.model import Registration

APPLYABLE_STATUSES = {"published", "ongoing"}
REVIEW_TARGETS = {"approved", "rejected", "waitlisted"}
CANCELLABLE_STATUSES = {"pending", "approved", "waitlisted"}
TERMINAL_STATUSES = {"cancelled", "rejected"}


@dataclass(frozen=True)
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


class _RegistrationBase:
    """Shared constructor and guard helpers for both reg services."""

    def __init__(
        self,
        registrations: RegistrationStore,
        attendance: AttendanceStore,
        activities: ActivityStore,
        orgs: OrgRepository,
        users: UserDirectory,
        access: AccessControl,
        notifications: NotificationPort | None = None,
        hours: HourRecorder | None = None,
        events: AttendanceEvents | None = None,
    ) -> None:
        self._registrations = registrations
        self._attendance = attendance
        self._activities = activities
        self._orgs = orgs
        self._users = users
        self._access = access
        self._notifications = notifications
        self._hours = hours
        self._events = events

    def _activity(self, activity_id: UUID) -> object:
        row = self._activities.get(activity_id)
        if row is None:
            raise NotFoundError("Activity not found.")
        return row

    def _require_manager(
        self, org_id: UUID, actor_id: UUID, action: str
    ) -> None:
        org = self._orgs.get_by_id(org_id)
        if org is None or getattr(org, "deleted_at", None) is not None:
            raise NotFoundError("Organization not found.")
        if (
            getattr(org, "owner_id", None) != actor_id
            and not self._access.has_permission(
                org_id, actor_id, "activity:manage"
            )
        ):
            self._access.record(
                org_id, actor_id, action, "registration", None, "denied"
            )
            raise ForbiddenError("Only org managers can do this.")

    def _notify(
        self, user_id: UUID, title: str, body: str = "", data=None
    ) -> None:
        if self._notifications is None:
            return
        try:
            self._notifications.notify(
                user_id, "registration", title, body,
                json.dumps(data) if data is not None else None,
            )
        except Exception:  # noqa: BLE001 - notifications are best-effort
            pass


class RegistrationService(_RegistrationBase):
    """Apply/review/cancel flows around the activity lifecycle."""

    def apply(
        self, activity_id: UUID, student_id: UUID, note: str | None
    ) -> Registration:
        """Published/ongoing activities accept applications until deadline."""
        activity = self._activity(activity_id)
        if activity.status not in APPLYABLE_STATUSES:
            raise RegistrationClosedError(
                "This activity is not accepting registrations."
            )
        deadline = getattr(activity, "registration_deadline", None)
        if deadline is not None and utcnow() > deadline:
            raise RegistrationClosedError(
                "The registration deadline has passed."
            )
        now = utcnow()
        guard = self._registrations.get_for_student(
            activity_id, student_id, UUID(int=0)
        )
        token = uuid7()
        if guard is not None and guard.status not in TERMINAL_STATUSES:
            from core.exceptions import AlreadyRegisteredError

            raise AlreadyRegisteredError(
                "You already registered for this activity."
            )
        if guard is not None:
            row = self._registrations.reapply(
                uuid7(), activity_id, student_id, note, token, now
            )
            from_status = guard.status
        else:
            row = self._registrations.create(
                activity_id, student_id, note, token, now
            )
            from_status = None
        self._registrations.record_history(
            row.registration_id, from_status, "pending", student_id,
            "application submitted", now,
        )
        return row

    def review(
        self,
        activity_id: UUID,
        registration_id: UUID,
        reviewer_id: UUID,
        target: str,
        review_note: str | None,
    ) -> Registration:
        """Managers approve, reject, or waitlist pending applications."""
        activity = self._activity(activity_id)
        self._require_manager(
            activity.org_id, reviewer_id, "registration.review"
        )
        if target not in REVIEW_TARGETS:
            raise InvalidRegistrationStateError(
                "Review target must be approved|rejected|waitlisted."
            )
        row = self._registrations.get(registration_id)
        if row is None or row.activity_id != activity_id:
            raise NotFoundError("Registration not found.")
        if row.status != "pending" and not (
            row.status == "waitlisted" and target == "approved"
        ):
            raise InvalidRegistrationStateError(
                f"Cannot move {row.status} to {target}."
            )
        now = utcnow()
        updated = self._registrations.set_status(
            registration_id, target, reviewer_id, review_note, now
        )
        assert updated is not None
        self._registrations.record_history(
            registration_id, row.status, target, reviewer_id,
            review_note, now,
        )
        self._access.record(
            activity.org_id, reviewer_id, f"registration.{target}",
            "registration", registration_id, "allowed",
        )
        label = {"approved": "\u0111\u01b0\u1ee3c duy\u1ec7t", "rejected": "b\u1ecb t\u1eeb ch\u1ed1i",
                 "waitlisted": "\u0111\u01b0a v\u00e0o danh s\u00e1ch ch\u1edd"}[target]
        self._notify(
            row.student_id,
            f"\u0110\u0103ng k\u00fd {label}",
            f"\u0110\u01a1n tham gia {activity.title} {label}.",
            {
                "activity_id": str(activity_id),
                "org_id": str(activity.org_id),
                "activity_slug": activity.slug,
            },
        )
        return updated

    def cancel(
        self,
        activity_id: UUID,
        registration_id: UUID,
        student_id: UUID,
    ) -> Registration:
        """Applicants withdraw live applications; history keeps the audit."""
        activity = self._activity(activity_id)
        row = self._registrations.get(registration_id)
        if row is None or row.activity_id != activity_id:
            raise NotFoundError("Registration not found.")
        if row.student_id != student_id:
            raise ForbiddenError("Only the applicant can cancel.")
        if row.status not in CANCELLABLE_STATUSES:
            raise InvalidRegistrationStateError(
                f"A {row.status} registration cannot be cancelled."
            )
        now = utcnow()
        updated = self._registrations.set_status(
            registration_id, "cancelled", None, None, now
        )
        assert updated is not None
        self._registrations.record_history(
            registration_id, row.status, "cancelled", student_id,
            None, now,
        )
        return updated

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
                    else "Ng\u01b0\u1eddi d\u00f9ng"
                ),
                student_email=brief.email if brief else None,
                status=row.status,
                note=row.note,
                review_note=row.review_note,
                registered_at=row.registered_at,
            )
            for row in rows
        ]

    def list_mine(self, student_id: UUID) -> list[Registration]:
        """Applicant's own history, newest first."""
        return self._registrations.list_by_student(student_id)

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
