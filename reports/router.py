"""HTTP layer for report snapshots + export jobs."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response

from core.dependencies import CurrentUser, get_current_user
from core.dependencies_reports import get_report_service
from reports.schemas import (
    ExportCreateRequest,
    ExportItem,
    SnapshotCreateRequest,
    SnapshotItem,
)
from reports.service import ReportService

router = APIRouter(tags=["reports"])


@router.post(
    "/orgs/{org_id}/snapshots",
    response_model=SnapshotItem,
    status_code=201,
)
def create_snapshot(
    org_id: UUID,
    body: SnapshotCreateRequest,
    current: CurrentUser = Depends(get_current_user),
    service: ReportService = Depends(get_report_service),
) -> SnapshotItem:
    """Capture the current org stats into an immutable snapshot."""
    view = service.create_snapshot(
        org_id, current.id, body.report_type,
        body.period_start, body.period_end,
    )
    return SnapshotItem(**vars(view))


@router.get("/orgs/{org_id}/snapshots", response_model=list[SnapshotItem])
def list_snapshots(
    org_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: ReportService = Depends(get_report_service),
) -> list[SnapshotItem]:
    """List the org's snapshots, newest first."""
    return [SnapshotItem(**vars(v)) for v in service.list_snapshots(org_id, current.id)]


@router.post("/export-jobs", response_model=ExportItem, status_code=201)
def request_export(
    body: ExportCreateRequest,
    org_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: ReportService = Depends(get_report_service),
) -> ExportItem:
    """Queue a CSV export; the file_url streams once done."""
    view = service.request_export(
        org_id, current.id, body.job_type, body.activity_id
    )
    return ExportItem(**vars(view))


@router.get("/export-jobs", response_model=list[ExportItem])
def list_mine(
    current: CurrentUser = Depends(get_current_user),
    service: ReportService = Depends(get_report_service),
) -> list[ExportItem]:
    """List the caller's export jobs, newest first."""
    return [ExportItem(**vars(v)) for v in service.list_mine(current.id)]


@router.get("/export-jobs/{job_id}/download")
def download_export(
    job_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: ReportService = Depends(get_report_service),
) -> Response:
    """Stream the finished CSV for one of the caller's jobs."""
    filename, text = service.download(current.id, job_id)
    return Response(
        content=text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
