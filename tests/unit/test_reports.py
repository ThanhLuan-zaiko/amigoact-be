"""reports: snapshots + export jobs (roster/stats CSV)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from core.exceptions import (
    ForbiddenError,
    InvalidBusinessProfileError,
    NotFoundError,
)
from core.ids import uuid7
from reports.interfaces import ExportJobStore, ReportStore
from reports.service import ReportService
from stats.interfaces import MonthlyStatsStore
from tests.unit.member_fakes import FakeAccess, FakeOrgs, FakeUsers
from tests.unit.registration_fakes import FakeRegistrations


class FakeReports(ReportStore):
    def __init__(self) -> None:
        self.rows: list[Any] = []

    def create(self, org_id, snapshot_id, report_type, period_start, period_end, payload_json, created_by, now):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            org_id=org_id, created_at=now, snapshot_id=snapshot_id,
            report_type=report_type, period_start=period_start,
            period_end=period_end, payload_json=payload_json,
            created_by=created_by,
        )
        self.rows.insert(0, row)
        return row

    def list_for_org(self, org_id, limit=20):  # noqa: ANN001, ANN202
        return [r for r in self.rows if r.org_id == org_id][:limit]


class FakeJobs(ExportJobStore):
    def __init__(self) -> None:
        self.rows: dict[UUID, Any] = {}

    def create(self, job_id, requested_by, org_id, job_type, status, now):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            requested_by=requested_by, created_at=now, job_id=job_id,
            org_id=org_id, job_type=job_type, status=status,
            file_url=None, error=None, finished_at=None,
        )
        self.rows[job_id] = row
        return row

    def get(self, requested_by, job_id):  # noqa: ANN001, ANN202
        row = self.rows.get(job_id)
        return row if row is not None and row.requested_by == requested_by else None

    def find(self, job_id, requester_ids):  # noqa: ANN001, ANN202
        row = self.rows.get(job_id)
        return row if row is not None and row.requested_by in requester_ids else None

    def list_mine(self, requested_by, limit=20):  # noqa: ANN001, ANN202
        rows = [r for r in self.rows.values() if r.requested_by == requested_by]
        return sorted(rows, key=lambda r: r.created_at, reverse=True)[:limit]

    def set_status(self, requested_by, job_id, status, file_url, error, now):  # noqa: ANN001, ANN202
        row = self.get(requested_by, job_id)
        if row is not None:
            row.status, row.file_url, row.error, row.finished_at = (
                status, file_url, error, now,
            )


class FakeMonthly(MonthlyStatsStore):
    def __init__(self) -> None:
        self.rows: dict[tuple, Any] = {}

    def upsert(self, org_id, month, activities, participants, hours, certificates):  # noqa: ANN001, ANN202
        self.rows[(org_id, month)] = SimpleNamespace(
            org_id=org_id, month=month, activities=activities,
            participants=participants, hours=hours, certificates=certificates,
        )

    def list_months(self, org_id, limit=12):  # noqa: ANN001, ANN202
        rows = [r for k, r in self.rows.items() if k[0] == org_id]
        return sorted(rows, key=lambda r: r.month, reverse=True)[:limit]


def _setup() -> tuple[ReportService, dict[str, Any], UUID, UUID]:
    snapshots = FakeReports()
    jobs = FakeJobs()
    monthly = FakeMonthly()
    regs = FakeRegistrations()
    orgs = FakeOrgs()
    access = FakeAccess()
    users = FakeUsers()
    owner = uuid7()
    org_id = uuid7()
    orgs.add(org_id, owner)
    service = ReportService(
        snapshots=snapshots, jobs=jobs, monthly=monthly,
        registrations=regs, orgs=orgs, access=access, users=users,
    )
    parts = {
        "snapshots": snapshots, "jobs": jobs, "monthly": monthly,
        "regs": regs, "orgs": orgs, "access": access, "users": users,
    }
    return service, parts, org_id, owner


def test_snapshot_records_months() -> None:
    service, parts, org_id, owner = _setup()
    parts["monthly"].upsert(org_id, "2026-01", 3, 10, 40.0, 2)
    view = service.create_snapshot(org_id, owner, "participation", None, None)
    assert view.payload["months"][0]["month"] == "2026-01"
    assert len(service.list_snapshots(org_id, owner)) == 1


def test_export_stats_csv_download() -> None:
    service, parts, org_id, owner = _setup()
    parts["monthly"].upsert(org_id, "2026-02", 1, 5, 12.5, 0)
    job = service.request_export(org_id, owner, "stats_csv")
    assert job.status == "done" and job.file_url
    filename, text = service.download(owner, job.job_id)
    assert filename.endswith(".csv") and "2026-02" in text


def test_export_roster_csv_rows() -> None:
    service, parts, org_id, owner = _setup()
    activity_id = uuid7()
    student = uuid7()
    parts["users"].add(student, "s@x.com", name="Sinh Vi\xean")
    parts["regs"].create(
        activity_id, student, "note", "tok",
        datetime.now(timezone.utc),
    )
    job = service.request_export(org_id, owner, "roster_csv", activity_id)
    _, text = service.download(owner, job.job_id)
    assert "Sinh Vi\xean" in text and str(student) in text


def test_export_validation_and_permissions() -> None:
    service, parts, org_id, owner = _setup()
    with pytest.raises(InvalidBusinessProfileError):
        service.request_export(org_id, owner, "bogus")
    with pytest.raises(InvalidBusinessProfileError):
        service.request_export(org_id, owner, "roster_csv")
    outsider = uuid7()
    with pytest.raises(ForbiddenError):
        service.request_export(org_id, outsider, "stats_csv")
    with pytest.raises(NotFoundError):
        service.download(owner, uuid7())
