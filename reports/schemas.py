"""Request/response DTOs for report snapshots + export jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SnapshotCreateRequest(BaseModel):
    """Snapshot body: report type plus an optional period window."""

    report_type: str = Field(min_length=3, max_length=40)
    period_start: datetime | None = None
    period_end: datetime | None = None


class SnapshotItem(BaseModel):
    """One saved snapshot row with its parsed payload."""

    snapshot_id: UUID
    report_type: str
    period_start: datetime | None = None
    period_end: datetime | None = None
    payload: dict[str, Any]
    created_by: UUID
    created_at: datetime | None = None


class ExportCreateRequest(BaseModel):
    """Export body: job type; roster needs the activity id."""

    job_type: str = Field(min_length=3, max_length=40)
    activity_id: UUID | None = None


class ExportItem(BaseModel):
    """Job row as listed for the requester."""

    job_id: UUID
    org_id: UUID
    job_type: str
    status: str
    file_url: str | None = None
    error: str | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None
