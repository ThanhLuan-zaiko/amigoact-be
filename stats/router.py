"""HTTP surface for org statistics (thin router)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends

from core.dependencies import CurrentUser, get_current_user
from core.dependencies_features import get_stats_service
from stats.schemas import OrgStatsResponse

if TYPE_CHECKING:
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
