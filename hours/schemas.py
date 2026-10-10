"""Request/response DTOs for the volunteer-hours API surface."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ManualHoursBody(BaseModel):
    """Staff-entered hours for one student on one activity."""

    student_id: UUID
    activity_id: UUID
    hours: float = Field(gt=0, le=1000)
    note: str | None = Field(default=None, max_length=500)


class ReviewHoursBody(BaseModel):
    """Approve or reject one pending ledger entry."""

    status: str = Field(pattern="^(approved|rejected)$")
    note: str | None = Field(default=None, max_length=500)


class HourEntryResponse(BaseModel):
    entry_id: UUID
    student_id: UUID
    activity_id: UUID
    source: str
    hours: float
    term: str
    status: str
    note: str | None
    recorded_at: datetime | None
    approved_at: datetime | None


class PendingHourResponse(BaseModel):
    entry_id: UUID
    student_id: UUID
    activity_id: UUID
    hours: float
    recorded_at: datetime


class MyLedgerItem(BaseModel):
    entry_id: UUID
    activity_id: UUID
    source: str | None
    hours: float | None
    status: str | None
    recorded_at: datetime


class HoursSummaryResponse(BaseModel):
    term: str
    total_hours: float
    activities_count: int


class MyHoursResponse(BaseModel):
    entries: list[MyLedgerItem]
    summaries: list[HoursSummaryResponse]


class LeaderboardEntryResponse(BaseModel):
    student_id: UUID
    student_name: str | None
    total_hours: float
    rank: int


class LeaderboardResponse(BaseModel):
    term: str
    entries: list[LeaderboardEntryResponse]
