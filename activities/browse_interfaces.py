"""Ports for the public browse feed and the signed-in 'my registrations' view."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from activities.model import Activity


@dataclass(frozen=True)
class MyRegistrationBrief:
    """The signed-in user's best registration on one activity."""

    registration_id: UUID
    status: str
    registered_at: datetime | None


class BrowseIndex(ABC):
    """Bounded candidate reads over the denormalized feeds, plus hydration."""

    @abstractmethod
    def candidates(self, phase: str, now: datetime) -> tuple[list[UUID], bool]:
        """Activity ids for one phase window from the status feeds.

        Tag and category filters are applied in memory, never by narrowing
        the read: a narrowed read would hide the other values the facets
        need to count. The flag is True when a source held more rows than
        the window keeps, so the caller can say the list is not exhaustive.
        """

    @abstractmethod
    def hydrate(self, ids: list[UUID]) -> list[Activity]:
        """Full rows for the ids, in the order given; unknown ids drop out."""


class SeatCounter(ABC):
    """Seat usage: approved and attended registrations hold a seat."""

    @abstractmethod
    def registered_count(self, activity_id: UUID) -> int:
        """Seats taken on one activity, the figure apply() compares to capacity."""


class RegistrationBriefs(ABC):
    """Per-student summary: one best registration per activity id."""

    @abstractmethod
    def briefs_for(self, student_id: UUID) -> dict[UUID, MyRegistrationBrief]:
        """Best registration keyed by activity id, for one student."""
