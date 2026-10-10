"""Review business rules: attended-only writes, dedup, public reads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from activities.interfaces import ActivityStore
from core.exceptions import (
    InvalidRegistrationStateError,
    NotFoundError,
    ReviewExistsError,
)
from core.ids import uuid7
from core.security import utcnow
from notifications.interfaces import NotificationPort
from orgs.interfaces import OrgRepository, UserDirectory
from registrations.interfaces import RegistrationStore
from reviews.interfaces import ReviewStore
from reviews.model import ReviewsByActivity

_WHOLE_ACTIVITY = UUID(int=0)


@dataclass(frozen=True)
class ReviewView:
    """Feed row joined with the reviewer's display name."""

    review_id: UUID
    activity_id: UUID
    student_id: UUID
    student_name: str
    rating: int
    comment: str | None
    created_at: datetime


class ReviewService:
    """One review per attended volunteer per activity."""

    def __init__(
        self,
        reviews: ReviewStore,
        activities: ActivityStore,
        registrations: RegistrationStore,
        orgs: OrgRepository,
        users: UserDirectory,
        notifications: NotificationPort | None = None,
    ) -> None:
        self._reviews = reviews
        self._activities = activities
        self._registrations = registrations
        self._orgs = orgs
        self._users = users
        self._notifications = notifications

    def create(
        self,
        activity_id: UUID,
        student_id: UUID,
        rating: int,
        comment: str | None,
    ) -> ReviewView:
        """Attended volunteers rate a finished activity, once each."""
        activity = self._activities.get(activity_id)
        if activity is None:
            raise NotFoundError("Activity not found.")
        guard = self._registrations.get_for_student(
            activity_id, student_id, _WHOLE_ACTIVITY
        )
        if guard is None or guard.status != "attended":
            raise InvalidRegistrationStateError(
                "Only attended volunteers can review this activity."
            )
        for row in self._reviews.list_by_student(student_id):
            if row.activity_id == activity_id:
                raise ReviewExistsError(
                    "You already reviewed this activity."
                )
        now = utcnow()
        row = self._reviews.add(
            uuid7(), activity_id, student_id, rating, comment, now
        )
        self._notify_owner(activity.org_id, activity.title, rating)
        return self._view(row)

    def _notify_owner(
        self, org_id: UUID, activity_title: str, rating: int
    ) -> None:
        if self._notifications is None:
            return
        org = self._orgs.get_by_id(org_id)
        if org is None or getattr(org, "owner_id", None) is None:
            return
        try:
            self._notifications.notify(
                org.owner_id,
                "review",
                "Đánh giá mới",
                f'"{activity_title}" nhận {rating}/5 sao.',
                None,
            )
        except Exception:  # noqa: BLE001 - notifications are best-effort
            pass

    def _view(self, row: ReviewsByActivity) -> ReviewView:
        brief = self._users.get_brief(row.student_id)
        name = (
            brief.full_name
            if brief is not None and brief.full_name
            else row.student_id.hex[:12]
        )
        return ReviewView(
            review_id=row.review_id,
            activity_id=row.activity_id,
            student_id=row.student_id,
            student_name=name,
            rating=row.rating or 0,
            comment=row.comment,
            created_at=row.created_at,
        )

    def list_for_activity(
        self, activity_id: UUID, limit: int = 50
    ) -> list[ReviewView]:
        """Public newest-first reviews of one activity."""
        return [
            self._view(row)
            for row in self._reviews.list_for_activity(
                activity_id, limit
            )
        ]

    def can_review(self, activity_id: UUID, student_id: UUID) -> bool:
        """Eligibility flag for the UI (attended, not yet reviewed)."""
        guard = self._registrations.get_for_student(
            activity_id, student_id, _WHOLE_ACTIVITY
        )
        if guard is None or guard.status != "attended":
            return False
        return all(
            row.activity_id != activity_id
            for row in self._reviews.list_by_student(student_id)
        )
