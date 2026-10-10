"""Abstract ports for the volunteer-hours bounded context (DIP wiring)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from hours.model import (
    HourEntriesByStudent,
    HoursByActivity,
    HoursByStudent,
    LeaderboardByTerm,
    PendingHoursByOrg,
    VolunteerHourEntry,
)


class HourLedgerStore(ABC):
    """Persistence port for ledger entries, feeds, and the org queue."""

    @abstractmethod
    def record(
        self,
        entry_id: UUID,
        org_id: UUID,
        student_id: UUID,
        activity_id: UUID,
        source: str,
        hours: float,
        term: str,
        registration_id: UUID | None,
        recorded_by: UUID | None,
        note: str | None,
        now: datetime,
    ) -> VolunteerHourEntry:
        """Append one pending ledger row plus activity/student/queue feeds."""

    @abstractmethod
    def get(self, entry_id: UUID) -> VolunteerHourEntry | None:
        """Load one ledger entry by primary key."""

    @abstractmethod
    def set_status(
        self,
        entry: VolunteerHourEntry,
        org_id: UUID,
        status: str,
        reviewer_id: UUID,
        now: datetime,
    ) -> VolunteerHourEntry:
        """Transition status, drop the queue row, sync feeds, roll up."""

    @abstractmethod
    def list_pending(
        self, org_id: UUID, limit: int = 100
    ) -> list[PendingHoursByOrg]:
        """Manager queue rows, oldest first."""

    @abstractmethod
    def list_by_student(
        self, student_id: UUID, limit: int = 100
    ) -> list[HourEntriesByStudent]:
        """One student's ledger history, newest first."""

    @abstractmethod
    def list_by_activity(
        self, activity_id: UUID, limit: int = 100
    ) -> list[HoursByActivity]:
        """One activity's ledger feed, newest first."""

    @abstractmethod
    def summary_for_student(
        self, student_id: UUID
    ) -> list[HoursByStudent]:
        """Approved-hours rollups, one row per term."""


class LeaderboardStore(ABC):
    """Persistence port for the ranked term leaderboard feed."""

    @abstractmethod
    def put(
        self,
        term: str,
        student_id: UUID,
        student_name: str,
        previous_total: float,
        new_total: float,
        now: datetime,
    ) -> None:
        """Move the student's row to its new total and register the term."""

    @abstractmethod
    def top(
        self, term: str, limit: int = 50
    ) -> list[LeaderboardByTerm]:
        """Highest-total rows first for one term board."""

    @abstractmethod
    def terms(self) -> list[str]:
        """All terms ever written, including 'all'."""


class HourRecorder(ABC):
    """Narrow port AttendanceService calls after check-out completes."""

    @abstractmethod
    def record_attendance(
        self,
        org_id: UUID,
        activity_id: UUID,
        student_id: UUID,
        registration_id: UUID | None,
        hours: float,
        recorded_by: UUID,
    ) -> None:
        """Queue one attendance-sourced ledger entry for approval."""
