"""Abstract ports for the registrations bounded context (DIP wiring)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from registrations.model import (
    AttendanceByRegistration,
    AttendanceRecord,
    Registration,
    RegistrationStatusHistory,
    RegistrationsByActivityStudent,
    RegistrationsByToken,
    WaitlistEntry,
)


class RegistrationStore(ABC):
    """Persistence port for applications plus their query feeds."""

    @abstractmethod
    def create(
        self,
        activity_id: UUID,
        student_id: UUID,
        note: str | None,
        checkin_token: UUID,
        now: datetime,
        status: str = "pending",
        form_data: str | None = None,
        slot_id: UUID | None = None,
    ) -> Registration:
        """Insert the row plus roster/student/token feeds."""

    @abstractmethod
    def reapply(
        self,
        registration_id: UUID,
        activity_id: UUID,
        student_id: UUID,
        note: str | None,
        checkin_token: UUID,
        now: datetime,
        status: str = "pending",
        form_data: str | None = None,
        slot_id: UUID | None = None,
    ) -> Registration:
        """Reopen a terminal guard row (cancelled/rejected)."""

    @abstractmethod
    def get(self, registration_id: UUID) -> Registration | None:
        """Load one application by primary key."""

    @abstractmethod
    def get_for_student(
        self, activity_id: UUID, student_id: UUID, slot_id: UUID
    ) -> RegistrationsByActivityStudent | None:
        """Duplicate-guard lookup in the activity/student table."""

    @abstractmethod
    def get_by_token(
        self, checkin_token: UUID
    ) -> RegistrationsByToken | None:
        """Resolve a personal QR token to its registration."""

    @abstractmethod
    def set_status(
        self,
        registration_id: UUID,
        status: str,
        reviewer_id: UUID | None,
        review_note: str | None,
        now: datetime,
    ) -> Registration | None:
        """Transition status and mirror it across every feed."""

    @abstractmethod
    def list_by_activity(
        self, activity_id: UUID, limit: int = 200
    ) -> list[Registration]:
        """Manager roster of one activity, oldest first."""

    @abstractmethod
    def list_by_student(
        self, student_id: UUID, limit: int = 100
    ) -> list[Registration]:
        """Student's applications, newest first."""

    @abstractmethod
    def count_active(
        self, activity_id: UUID, slot_id: UUID | None = None
    ) -> int:
        """Approved/attended registrations occupying capacity slots."""

    @abstractmethod
    def enqueue_waitlist(
        self,
        activity_id: UUID,
        student_id: UUID,
        slot_id: UUID,
        now: datetime,
    ) -> WaitlistEntry:
        """Append a student to the activity's FIFO waitlist."""

    @abstractmethod
    def list_waitlist(
        self, activity_id: UUID, status: str = "waiting", limit: int = 200
    ) -> list[WaitlistEntry]:
        """Waitlist entries oldest-first, filtered by entry status."""

    @abstractmethod
    def mark_waitlist(
        self,
        activity_id: UUID,
        joined_at: datetime,
        waitlist_id: UUID,
        status: str,
        promoted_at: datetime | None,
    ) -> None:
        """Flip one waitlist entry to promoted/expired."""

    @abstractmethod
    def list_history(
        self, registration_id: UUID, limit: int = 50
    ) -> list[RegistrationStatusHistory]:
        """Audit rows of one registration, newest first."""

    @abstractmethod
    def record_history(
        self,
        registration_id: UUID,
        from_status: str | None,
        to_status: str,
        changed_by: UUID,
        note: str | None,
        now: datetime,
    ) -> None:
        """Append one row to the per-registration audit feed."""


class AttendanceStore(ABC):
    """Persistence port for check-in/out records and feeds."""

    @abstractmethod
    def create(
        self,
        registration_id: UUID,
        activity_id: UUID,
        student_id: UUID,
        session_id: UUID | None,
        method: str,
        verified_by: UUID | None,
        now: datetime,
    ) -> AttendanceRecord:
        """Insert check-in plus registration/activity/student feeds."""

    @abstractmethod
    def get_for_registration(
        self, registration_id: UUID
    ) -> AttendanceByRegistration | None:
        """Duplicate-check lookup before writing check-in."""

    @abstractmethod
    def get(self, record_id: UUID) -> AttendanceRecord | None:
        """Load one attendance record."""

    @abstractmethod
    def check_out(
        self,
        record_id: UUID,
        method: str,
        actual_hours: float | None,
        now: datetime,
    ) -> AttendanceRecord | None:
        """Stamp check-out time, method, and computed hours."""

    @abstractmethod
    def list_by_activity(
        self, activity_id: UUID, limit: int = 200
    ) -> list[AttendanceRecord]:
        """All check-ins of one activity, newest first."""

    @abstractmethod
    def list_by_student(
        self, student_id: UUID, limit: int = 100
    ) -> list[AttendanceRecord]:
        """One student's check-ins across activities."""

class AttendanceEvents(ABC):
    """Fan-out port: one live event per committed attendance mutation."""

    @abstractmethod
    def attendance_changed(
        self,
        activity_id: UUID,
        action: str,
        record_id: UUID,
        student_id: UUID,
        actor_id: UUID,
    ) -> None:
        """Publish check-in/out onto the attendance:{activity_id} channel."""


class SeatEvents(ABC):
    """Fan-out port: seat counts moved (review or cancel) on events:feed."""

    @abstractmethod
    def seats_changed(self, activity_id: UUID, org_id: UUID) -> None:
        """Public hint only; the browse feed refetches its own numbers."""


class RegistrationBriefStore(ABC):
    """Read port: one student's registration rows across activities."""

    @abstractmethod
    def student_rows(self, student_id: UUID, limit: int = 500) -> list:
        """Newest-first registration rows for one student."""
