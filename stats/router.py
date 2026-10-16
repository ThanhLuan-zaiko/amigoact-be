"""HTTP surface for org statistics (thin router)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends

from core.dependencies import CurrentUser, get_current_user
from core.dependencies_features import get_projection_service, get_stats_service
from stats.schemas import DailyStatsItem, MonthlyStatsItem, OrgStatsResponse

if TYPE_CHECKING:
    from stats.projection_service import StatsProjectionService
    from stats.service import OrgStatsService

router = APIRouter(tags=["stats"])


@router.get("/orgs/{org_id}/stats", response_model=OrgStatsResponse)
def org_stats(
    org_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: OrgStatsService = Depends(get_stats_service),
) -> OrgStatsResponse:
    """Manager dashboard numbers for one org."""
    stats = service.org_stats(org_id, current.id)
    return OrgStatsResponse(
        activities_total=stats.activities_total,
        members_total=stats.members_total,
        participants_total=stats.participants_total,
        hours_approved=stats.hours_approved,
        hours_pending=stats.hours_pending,
        certificates_issued=stats.certificates_issued,
    )


@router.get(
    "/activities/{activity_id}/stats/daily",
    response_model=list[DailyStatsItem],
)
def activity_daily_stats(
    activity_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: StatsProjectionService = Depends(get_projection_service),
) -> list[DailyStatsItem]:
    """Manager reads the materialized per-day rollup."""
    return [
        DailyStatsItem(
            day=r.day,
            registrations=r.registrations or 0,
            attendees=r.attendees or 0,
            hours_awarded=r.hours_awarded or 0.0,
        )
        for r in service.activity_daily(activity_id, current.id)
    ]


@router.get(
    "/orgs/{org_id}/stats/monthly",
    response_model=list[MonthlyStatsItem],
)
def org_monthly_stats(
    org_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: StatsProjectionService = Depends(get_projection_service),
) -> list[MonthlyStatsItem]:
    """Manager reads the materialized per-month rollup."""
    return [
        MonthlyStatsItem(
            month=r.month,
            activities=r.activities or 0,
            participants=r.participants or 0,
            hours=r.hours or 0.0,
            certificates=r.certificates or 0,
        )
        for r in service.org_monthly(org_id, current.id)
    ]
