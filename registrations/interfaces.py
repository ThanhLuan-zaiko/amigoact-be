"""Abstract ports for the registrations bounded context (DIP wiring)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from registrations.model import (
    AttendanceByRegistration,
    AttendanceRecord,
    Registration,
    RegistrationsByActivityStudent,
    RegistrationsByToken,
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
    ) -> Registration:
        """Insert pending row plus roster/student/token feeds."""

    @abstractmethod
    def reapply(
        self,
        registration_id: UUID,
        activity_id: UUID,
        student_id: UUID,
        note: str | None,
        checkin_token: UUID,
        now: datetime,
    ) -> Registration:
        """Reopen a terminal guard row (cancelled/rejected) as pending."""

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
