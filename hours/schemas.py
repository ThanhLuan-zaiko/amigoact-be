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


class HourRuleBody(BaseModel):
    """Create a per-org multiplier rule (optional cap/scope)."""

    multiplier: float = Field(gt=0)
    category_id: UUID | None = None
    cap_hours: float | None = Field(default=None, gt=0)
    term: str | None = Field(default=None, max_length=20)


class HourRulePatchBody(BaseModel):
    """Toggle a rule without mutating its values."""

    is_active: bool


class HourRuleResponse(BaseModel):
    """One rule row as the manager list shows it."""

    rule_id: UUID
    org_id: UUID
    category_id: UUID | None
    multiplier: float | None
    cap_hours: float | None
    term: str | None
    is_active: bool | None


class AdjustHoursBody(BaseModel):
    """Staff correction: audit row plus a queued ledger entry."""

    student_id: UUID
    activity_id: UUID
    delta_hours: float
    reason: str = Field(min_length=3, max_length=500)


class AdjustmentResponse(BaseModel):
    """Audit row returned after queueing the correction."""

    adjustment_id: UUID
    student_id: UUID
    activity_id: UUID
    delta_hours: float
    reason: str | None
    created_by: UUID | None
    created_at: datetime | None
