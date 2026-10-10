"""Response DTO for the org stats endpoint."""

from __future__ import annotations

from pydantic import BaseModel


class OrgStatsResponse(BaseModel):
    activities_total: int
    members_total: int
    participants_total: int
    hours_approved: float
    hours_pending: int
    certificates_issued: int
