"""cqlengine persistence for reports."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from reports.interfaces import ExportJobStore, ReportStore
from reports.model import ExportJob, ReportSnapshot


class CqlReportStore(ReportStore):
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
        return ReportSnapshot.create(
            org_id=org_id,
            created_at=now,
            snapshot_id=snapshot_id,
            report_type=report_type,
            period_start=period_start,
            period_end=period_end,
            payload_json=payload_json,
            created_by=created_by,
        )

    def list_for_org(self, org_id: UUID, limit: int = 20) -> list[ReportSnapshot]:
        return list(
            ReportSnapshot.objects(org_id=org_id).limit(limit).all()
        )


class CqlExportJobStore(ExportJobStore):
    def create(
        self,
        job_id: UUID,
        requested_by: UUID,
        org_id: UUID,
        job_type: str,
        status: str,
        now: datetime,
    ) -> ExportJob:
        return ExportJob.create(
            requested_by=requested_by,
            created_at=now,
            job_id=job_id,
            org_id=org_id,
            job_type=job_type,
            status=status,
        )

    def get(self, requested_by: UUID, job_id: UUID) -> ExportJob | None:
        for row in ExportJob.objects(requested_by=requested_by).limit(50):
            if row.job_id == job_id:
                return row
        return None

    def find(self, job_id: UUID, requester_ids: list[UUID]) -> ExportJob | None:
        for requester in requester_ids:
            row = self.get(requester, job_id)
            if row is not None:
                return row
        return None

    def list_mine(self, requested_by: UUID, limit: int = 20) -> list[ExportJob]:
        return list(
            ExportJob.objects(requested_by=requested_by).limit(limit).all()
        )

    def set_status(
        self,
        requested_by: UUID,
        job_id: UUID,
        status: str,
        file_url: str | None,
        error: str | None,
        now: datetime,
    ) -> None:
        for row in ExportJob.objects(requested_by=requested_by).limit(50):
            if row.job_id == job_id:
                ExportJob.objects(
                    requested_by=requested_by, created_at=row.created_at,
                    job_id=job_id,
                ).update(status=status, file_url=file_url,
                         error=error, finished_at=now)
                return
