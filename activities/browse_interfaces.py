"""Ports for the public browse feed and the signed-in 'my registrations' view."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from activities.browse_window import Cursor, Cut
from activities.model import Activity


@dataclass(frozen=True)
class MyRegistrationBrief:
    """The signed-in user's best registration on one activity."""

    registration_id: UUID
    status: str
    registered_at: datetime | None


@dataclass(frozen=True)
class ScanPlan:
    """What one window reads: a public phase, or one organization's feed."""

    phase: str
    now: datetime
    starts_from: datetime | None
    starts_to: datetime | None
    org_id: UUID | None
    cursor: Cursor | None


@dataclass(frozen=True)
class CandidateWindow:
    """Activity ids for one window, and the cut that ends it."""

    ids: list[UUID]
    cut: Cut


class BrowseIndex(ABC):
    """Bounded candidate reads over the denormalized feeds, plus hydration."""

    @abstractmethod
    def candidates(self, plan: ScanPlan) -> CandidateWindow:
        """Activity ids for one window, narrowed by dates and cursor.

        Tag, category and city filters are applied in memory, never by
        narrowing the read: a narrowed read would hide the other values the
        facets need to count. The cut is set when a source held more rows
        than the window keeps, so the caller can offer the next window.
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


class QuickApplyProbe(ABC):
    """Whether an activity asks the applicant for anything beyond a click."""

    @abstractmethod
    def needs_input(self, activity_id: UUID) -> bool:
        """True when the activity has form questions or session slots."""
