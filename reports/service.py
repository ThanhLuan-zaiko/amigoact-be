"""Report snapshots + CSV export jobs."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from core.durability import JobLeaseStore
from core.exceptions import ForbiddenError, InvalidBusinessProfileError, NotFoundError
from core.ids import uuid7
from core.security import utcnow
from orgs.interfaces import OrgRepository, UserDirectory
from rbac.interfaces import AccessControl
from registrations.interfaces import RegistrationStore
from reports.interfaces import ExportJobStore, ReportStore
from stats.interfaces import MonthlyStatsStore

JOB_TYPES = {"roster_csv", "stats_csv"}
REPORT_TYPES = {"activity_summary", "hours_leaderboard", "participation"}


@dataclass(frozen=True)
class SnapshotView:
    snapshot_id: UUID
    report_type: str
    period_start: datetime | None
    period_end: datetime | None
    payload: dict
    created_by: UUID
    created_at: datetime | None


@dataclass(frozen=True)
class JobView:
    job_id: UUID
    org_id: UUID
    job_type: str
    status: str
    file_url: str | None
    error: str | None
    created_at: datetime | None
    finished_at: datetime | None


def _view(row) -> SnapshotView:
    return SnapshotView(
        snapshot_id=row.snapshot_id,
        report_type=row.report_type,
        period_start=row.period_start,
        period_end=row.period_end,
        payload=json.loads(row.payload_json),
        created_by=row.created_by,
        created_at=row.created_at,
    )


def _job_view(row) -> JobView:
    return JobView(
        job_id=row.job_id,
        org_id=row.org_id,
        job_type=row.job_type,
        status=row.status,
        file_url=row.file_url,
        error=row.error,
        created_at=row.created_at,
        finished_at=row.finished_at,
    )


class ReportService:
    """Snapshot + CSV export orchestration for org managers."""

    def __init__(
        self,
        snapshots: ReportStore,
        jobs: ExportJobStore,
        monthly: MonthlyStatsStore,
        registrations: RegistrationStore,
        orgs: OrgRepository,
        access: AccessControl,
        users: UserDirectory,
        leases: JobLeaseStore | None = None,
    ) -> None:
        self._snapshots = snapshots
        self._jobs = jobs
        self._monthly = monthly
        self._registrations = registrations
        self._orgs = orgs
        self._access = access
        self._users = users
        self._leases = leases

    def _require_manager(self, org_id: UUID, actor_id: UUID) -> None:
        org = self._orgs.get_by_id(org_id)
        if org is None or getattr(org, "deleted_at", None) is not None:
            raise NotFoundError("Organization not found.")
        if org.owner_id != actor_id and not self._access.has_permission(
            org_id, actor_id, "org:update"
        ):
            raise ForbiddenError("Only org managers can run reports.")

    def create_snapshot(
        self,
        org_id: UUID,
        actor_id: UUID,
        report_type: str,
        period_start: datetime | None,
        period_end: datetime | None,
    ) -> SnapshotView:
        self._require_manager(org_id, actor_id)
        if report_type not in REPORT_TYPES:
            raise InvalidBusinessProfileError("report_type is invalid.")
        payload = {
            "months": [
                {
                    "month": row.month,
                    "activities": row.activities,
                    "participants": row.participants,
                    "hours": row.hours,
                    "certificates": row.certificates,
                }
                for row in self._monthly.list_months(org_id, 12)
            ]
        }
        row = self._snapshots.create(
            org_id=org_id,
            snapshot_id=uuid7(),
            report_type=report_type,
            period_start=period_start,
            period_end=period_end,
            payload_json=json.dumps(payload),
            created_by=actor_id,
            now=utcnow(),
        )
        return _view(row)

    def list_snapshots(
        self, org_id: UUID, actor_id: UUID, limit: int = 20
    ) -> list[SnapshotView]:
        self._require_manager(org_id, actor_id)
        return [_view(row) for row in self._snapshots.list_for_org(org_id, limit)]

    def request_export(
        self,
        org_id: UUID,
        actor_id: UUID,
        job_type: str,
        activity_id: UUID | None = None,
    ) -> JobView:
        self._require_manager(org_id, actor_id)
        if job_type not in JOB_TYPES:
            raise InvalidBusinessProfileError("job_type is invalid.")
        if job_type == "roster_csv" and activity_id is None:
            raise InvalidBusinessProfileError("roster_csv needs activity_id.")
        job = self._jobs.create(
            job_id=uuid7(),
            requested_by=actor_id,
            org_id=org_id,
            job_type=job_type if activity_id is None else f"{job_type}:{activity_id}",
            status="queued",
            now=utcnow(),
        )
        # Synchronous pipeline: hold a job lease while the CSV renders so a
        # concurrent worker never double-processes the same export job.
        owner = f"api:{actor_id}"
        if self._leases is not None and not self._leases.acquire(
            job.job_id, owner, 300
        ):
            raise InvalidBusinessProfileError("Export job is already running.")
        try:
            self._jobs.set_status(
                actor_id,
                job.job_id,
                "done",
                f"/export-jobs/{job.job_id}/download",
                None,
                utcnow(),
            )
        finally:
            if self._leases is not None:
                self._leases.release(job.job_id, owner, "done")
        return _job_view(self._jobs.get(actor_id, job.job_id))

    def list_mine(self, user_id: UUID, limit: int = 20) -> list[JobView]:
        return [_job_view(row) for row in self._jobs.list_mine(user_id, limit)]

    def download(self, user_id: UUID, job_id: UUID) -> tuple[str, str]:
        """Return (filename, csv_text) for one of the caller's jobs."""
        row = self._jobs.get(user_id, job_id)
        if row is None:
            raise NotFoundError("Export job not found.")
        if row.status != "done":
            raise InvalidBusinessProfileError("Export is not finished yet.")
        if row.job_type.startswith("roster_csv"):
            activity_id = UUID(row.job_type.split(":", 1)[1])
            return f"roster-{activity_id}.csv", self._roster_csv(activity_id)
        return f"stats-{job_id}.csv", self._stats_csv(row.org_id)

    def _stats_csv(self, org_id: UUID) -> str:
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["month", "activities", "participants", "hours", "certificates"])
        for row in self._monthly.list_months(org_id, 24):
            writer.writerow([row.month, row.activities, row.participants, row.hours, row.certificates])
        return out.getvalue()

    def _name_of(self, user_id: UUID) -> str:
        brief = self._users.get_brief(user_id)
        return brief.full_name if brief is not None else ""

    def _roster_csv(self, activity_id: UUID) -> str:
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["activity_id", "user_id", "name", "status", "registered_at"])
        for row in self._registrations.list_by_activity(activity_id):
            writer.writerow(
                [
                    row.activity_id,
                    row.student_id,
                    self._name_of(row.student_id),
                    row.status,
                    row.registered_at,
                ]
            )
        return out.getvalue()
