"""Abstract ports for the reviews bounded context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from reviews.model import ReviewsByActivity, ReviewsByStudent


class ReviewStore(ABC):
    """Persistence port for review writes and both feed projections."""

    @abstractmethod
    def add(
        self,
        review_id: UUID,
        activity_id: UUID,
        student_id: UUID,
        rating: int,
        comment: str | None,
        now: datetime,
    ) -> ReviewsByActivity:
        """Write the activity feed row and the student-side mirror."""

    @abstractmethod
    def list_for_activity(
        self, activity_id: UUID, limit: int = 50
    ) -> list[ReviewsByActivity]:
        """Newest-first public reviews of one activity."""

    @abstractmethod
    def list_by_student(
        self, student_id: UUID, limit: int = 100
    ) -> list[ReviewsByStudent]:
        """One student's reviews, newest first (also the dedup index)."""
