"""Response DTO for the org stats endpoint."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class OrgStatsResponse(BaseModel):
    activities_total: int
    members_total: int
    participants_total: int
    hours_approved: float
    hours_pending: int
    certificates_issued: int


class DailyStatsItem(BaseModel):
    """One materialized per-day row for an activity."""

    day: date
    registrations: int
    attendees: int
    hours_awarded: float


class MonthlyStatsItem(BaseModel):
    """One materialized per-month row for an org."""

    month: str
    activities: int
    participants: int
    hours: float
    certificates: int
