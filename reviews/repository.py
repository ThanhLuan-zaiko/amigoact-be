"""cqlengine persistence for reviews (dual-feed writes)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from reviews.interfaces import ReviewStore
from reviews.model import ReviewsByActivity, ReviewsByStudent


class CqlReviewStore(ReviewStore):
    """Writes the activity feed plus the student-side mirror row."""

    def add(
        self,
        review_id: UUID,
        activity_id: UUID,
        student_id: UUID,
        rating: int,
        comment: str | None,
        now: datetime,
    ) -> ReviewsByActivity:
        row = ReviewsByActivity.create(
            activity_id=activity_id,
            created_at=now,
            review_id=review_id,
            student_id=student_id,
            rating=rating,
            comment=comment,
        )
        ReviewsByStudent.create(
            student_id=student_id,
            created_at=now,
            review_id=review_id,
            activity_id=activity_id,
            rating=rating,
        )
        return row

    def list_for_activity(
        self, activity_id: UUID, limit: int = 50
    ) -> list[ReviewsByActivity]:
        return list(
            ReviewsByActivity.objects(activity_id=activity_id).limit(
                limit
            )
        )

    def list_by_student(
        self, student_id: UUID, limit: int = 100
    ) -> list[ReviewsByStudent]:
        return list(
            ReviewsByStudent.objects(student_id=student_id).limit(limit)
        )
