"""Persistence ports for reports + exports."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from reports.model import ExportJob, ReportSnapshot


class ReportStore(ABC):
    """Snapshot rows keyed by (org_id, created_at desc)."""

    @abstractmethod
    def create(
        self,
        org_id: UUID,
        snapshot_id: UUID,
        report_type: str,
        period_start: datetime | None,
        period_end: datetime | None,
        payload_json: str,
        created_by: UUID,
        now: datetime,
    ) -> ReportSnapshot:
        """Insert one snapshot row."""

    @abstractmethod
    def list_for_org(self, org_id: UUID, limit: int = 20) -> list[ReportSnapshot]:
        """Most recent snapshots first."""


class ExportJobStore(ABC):
    """Job rows keyed by (requested_by, created_at desc)."""

    @abstractmethod
    def create(
        self,
        job_id: UUID,
        requested_by: UUID,
        org_id: UUID,
        job_type: str,
        status: str,
        now: datetime,
    ) -> ExportJob:
        """Insert one job row."""

    @abstractmethod
    def get(self, requested_by: UUID, job_id: UUID) -> ExportJob | None:
        """Load one job of the requester."""

    @abstractmethod
    def find(self, job_id: UUID, requester_ids: list[UUID]) -> ExportJob | None:
        """Locate a job when only job_id is known (small scan)."""

    @abstractmethod
    def list_mine(self, requested_by: UUID, limit: int = 20) -> list[ExportJob]:
        """Most recent jobs first."""

    @abstractmethod
    def set_status(
        self,
        requested_by: UUID,
        job_id: UUID,
        status: str,
        file_url: str | None,
        error: str | None,
        now: datetime,
    ) -> None:
        """Transition status and attach results."""
