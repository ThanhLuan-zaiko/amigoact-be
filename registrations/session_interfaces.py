"""Persistence ports for QR sessions, scan logs, appeals, summaries."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from registrations.model import (
    AttendanceAppeal,
    AttendanceSession,
    AttendanceSummary,
    QrCode,
    QrScanLog,
)


class SessionStore(ABC):
    """Persistence port for attendance sessions and their QR codes."""

    @abstractmethod
    def create(
        self,
        session_id: UUID,
        schedule_id: UUID,
        title: str,
        qr_code: str,
        opens_at: datetime | None,
        closes_at: datetime | None,
        status: str,
        created_by: UUID,
    ) -> AttendanceSession:
        """Insert one check-in window under a schedule."""

    @abstractmethod
    def list(self, schedule_id: UUID) -> list[AttendanceSession]:
        """All sessions of one schedule, clustered by session_id."""

    @abstractmethod
    def get(
        self, schedule_id: UUID, session_id: UUID
    ) -> AttendanceSession | None:
        """Load one session by its partition."""

    @abstractmethod
    def set_status(
        self, schedule_id: UUID, session_id: UUID, status: str
    ) -> bool:
        """Transition scheduled -> open -> closed."""


class QrStore(ABC):
    """Persistence port for scannable codes and usage counters."""

    @abstractmethod
    def create(
        self,
        code: str,
        session_id: UUID,
        schedule_id: UUID,
        activity_id: UUID,
        expires_at: datetime | None,
        max_uses: int | None,
    ) -> QrCode:
        """Mint one code bound to a session."""

    @abstractmethod
    def get(self, code: str) -> QrCode | None:
        """Resolve a scanned code."""

    @abstractmethod
    def set_status(self, code: str, status: str) -> None:
        """active -> disabled/expired."""

    @abstractmethod
    def bump_used(self, code: str) -> None:
        """Increment used_count after an accepted scan."""


class ScanLogStore(ABC):
    """Persistence port for the per-code audit feed."""

    @abstractmethod
    def log(
        self,
        qr_code: str,
        log_id: UUID,
        student_id: UUID,
        result: str,
        device_info: str | None,
        now: datetime,
    ) -> QrScanLog:
        """Append one scan outcome."""

    @abstractmethod
    def list(self, qr_code: str, limit: int = 200) -> list[QrScanLog]:
        """Newest scans first for one code."""


class AppealStore(ABC):
    """Persistence port for student attendance appeals."""

    @abstractmethod
    def create(
        self,
        activity_id: UUID,
        student_id: UUID,
        appeal_id: UUID,
        record_id: UUID | None,
        reason: str,
        now: datetime,
    ) -> AttendanceAppeal:
        """File one pending appeal."""

    @abstractmethod
    def list_by_activity(
        self, activity_id: UUID, limit: int = 200
    ) -> list[AttendanceAppeal]:
        """Manager queue, all students."""

    @abstractmethod
    def list_for_student(
        self, activity_id: UUID, student_id: UUID
    ) -> list[AttendanceAppeal]:
        """One student's appeals inside one activity."""

    @abstractmethod
    def get(
        self, activity_id: UUID, student_id: UUID, appeal_id: UUID
    ) -> AttendanceAppeal | None:
        """Load one appeal row."""

    @abstractmethod
    def resolve(
        self,
        activity_id: UUID,
        student_id: UUID,
        appeal_id: UUID,
        status: str,
        resolved_by: UUID,
        now: datetime,
    ) -> AttendanceAppeal | None:
        """Stamp the resolution."""


class SummaryStore(ABC):
    """Persistence port for materialized attendance rollups."""

    @abstractmethod
    def get(self, registration_id: UUID) -> AttendanceSummary | None:
        """Load the stored rollup if it exists."""

    @abstractmethod
    def upsert(
        self,
        registration_id: UUID,
        activity_id: UUID,
        student_id: UUID,
        sessions_total: int,
        sessions_attended: int,
        minutes_attended: int,
        status: str,
        now: datetime,
    ) -> AttendanceSummary:
        """Write the recomputed rollup."""
