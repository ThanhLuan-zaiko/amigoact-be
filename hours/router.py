"""HTTP surface for the volunteer-hours ledger (thin router)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends

from core.dependencies import CurrentUser, get_current_user
from core.dependencies_features import (
    get_hour_service,
    get_rule_service,
)
from hours.schemas import (
    AdjustHoursBody,
    AdjustmentResponse,
    HourEntryResponse,
    HourRuleBody,
    HourRulePatchBody,
    HourRuleResponse,
    LeaderboardEntryResponse,
    LeaderboardResponse,
    ManualHoursBody,
    MyHoursResponse,
    MyLedgerItem,
    HoursSummaryResponse,
    PendingHourResponse,
    ReviewHoursBody,
)

if TYPE_CHECKING:
    from hours.model import (
        HourAdjustment,
        HourEntriesByStudent,
        HourRule,
        PendingHoursByOrg,
        VolunteerHourEntry,
    )
    from hours.rule_service import RuleService
    from hours.service import HourService

router = APIRouter(tags=["hours"])


def _entry(row: VolunteerHourEntry) -> HourEntryResponse:
    return HourEntryResponse(
        entry_id=row.entry_id,
        student_id=row.student_id,
        activity_id=row.activity_id,
        source=row.source,
        hours=row.hours,
        term=row.term,
        status=row.status,
        note=row.note,
        recorded_at=row.recorded_at,
        approved_at=row.approved_at,
    )


def _pending(row: PendingHoursByOrg) -> PendingHourResponse:
    return PendingHourResponse(
        entry_id=row.entry_id,
        student_id=row.student_id,
        activity_id=row.activity_id,
        hours=row.hours,
        recorded_at=row.recorded_at,
    )


def _ledger_item(row: HourEntriesByStudent) -> MyLedgerItem:
    return MyLedgerItem(
        entry_id=row.entry_id,
        activity_id=row.activity_id,
        source=row.source,
        hours=row.hours,
        status=row.status,
        recorded_at=row.recorded_at,
    )


@router.post(
    "/orgs/{org_id}/hours",
    response_model=HourEntryResponse,
    status_code=201,
)
def submit_manual(
    org_id: UUID,
    body: ManualHoursBody,
    current: CurrentUser = Depends(get_current_user),
    service: HourService = Depends(get_hour_service),
) -> HourEntryResponse:
    """Staff-entered hours still join the approval queue."""
    return _entry(
        service.submit_manual(
            org_id, body.activity_id, body.student_id,
            body.hours, body.note, current.id,
        )
    )


@router.get(
    "/orgs/{org_id}/hours/pending",
    response_model=list[PendingHourResponse],
)
def pending_queue(
    org_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: HourService = Depends(get_hour_service),
) -> list[PendingHourResponse]:
    """Manager's approval queue for one org, oldest first."""
    return [
        _pending(row)
        for row in service.pending_queue(org_id, current.id)
    ]


@router.get(
    "/orgs/{org_id}/activities/{activity_id}/hours",
    response_model=list[HourEntryResponse],
)
def activity_ledger(
    org_id: UUID,
    activity_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: HourService = Depends(get_hour_service),
) -> list[HourEntryResponse]:
    """All ledger entries of one activity for reports."""
    return [
        _entry(row)
        for row in service.activity_ledger(
            org_id, activity_id, current.id
        )
    ]


@router.post(
    "/hours/{entry_id}/review", response_model=HourEntryResponse
)
def review(
    entry_id: UUID,
    body: ReviewHoursBody,
    current: CurrentUser = Depends(get_current_user),
    service: HourService = Depends(get_hour_service),
) -> HourEntryResponse:
    """Approve or reject a pending entry."""
    return _entry(
        service.review(entry_id, current.id, body.status, body.note)
    )


@router.get("/hours/mine", response_model=MyHoursResponse)
def my_hours(
    current: CurrentUser = Depends(get_current_user),
    service: HourService = Depends(get_hour_service),
) -> MyHoursResponse:
    """Student's ledger feed plus approved-hour rollups per term."""
    entries = service.my_ledger(current.id)
    summaries = service.my_summary(current.id)
    return MyHoursResponse(
        entries=[_ledger_item(row) for row in entries],
        summaries=[
            HoursSummaryResponse(
                term=s.term,
                total_hours=s.total_hours,
                activities_count=s.activities_count,
            )
            for s in summaries
        ],
    )


@router.get("/leaderboard", response_model=LeaderboardResponse)
def leaderboard(
    term: str = "all",
    limit: int = 50,
    service: HourService = Depends(get_hour_service),
) -> LeaderboardResponse:
    """Public ranked approved-hours board for one term ('all' = all-time)."""
    rows = service.leaderboard_top(term, min(limit, 100))
    return LeaderboardResponse(
        term=term,
        entries=[
            LeaderboardEntryResponse(
                student_id=row.student_id,
                student_name=row.student_name,
                total_hours=row.total_hours,
                rank=index + 1,
            )
            for index, row in enumerate(rows)
        ],
    )


@router.get("/leaderboard/terms", response_model=list[str])
def leaderboard_terms(
    service: HourService = Depends(get_hour_service),
) -> list[str]:
    """Public list of boards that have at least one ranked student."""
    return service.leaderboard_terms()


def _rule(row: HourRule) -> HourRuleResponse:
    return HourRuleResponse(
        rule_id=row.rule_id,
        org_id=row.org_id,
        category_id=row.category_id,
        multiplier=row.multiplier,
        cap_hours=row.cap_hours,
        term=row.term,
        is_active=row.is_active,
    )


@router.get(
    "/orgs/{org_id}/hour-rules",
    response_model=list[HourRuleResponse],
)
def list_rules(
    org_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: RuleService = Depends(get_rule_service),
) -> list[HourRuleResponse]:
    """Manager lists the org's multiplier/cap rules."""
    return [
        _rule(r) for r in service.list_rules(org_id, current.id)
    ]


@router.post(
    "/orgs/{org_id}/hour-rules",
    response_model=HourRuleResponse,
    status_code=201,
)
def create_rule(
    org_id: UUID,
    body: HourRuleBody,
    current: CurrentUser = Depends(get_current_user),
    service: RuleService = Depends(get_rule_service),
) -> HourRuleResponse:
    """Attach a multiplier to a category/term scope."""
    return _rule(
        service.create_rule(
            org_id, current.id, body.multiplier,
            body.category_id, body.cap_hours, body.term,
        )
    )


@router.patch(
    "/orgs/{org_id}/hour-rules/{rule_id}",
    response_model=HourRuleResponse,
)
def toggle_rule(
    org_id: UUID,
    rule_id: UUID,
    body: HourRulePatchBody,
    current: CurrentUser = Depends(get_current_user),
    service: RuleService = Depends(get_rule_service),
) -> HourRuleResponse:
    """Toggle a rule on/off; values stay immutable."""
    return _rule(
        service.set_rule_active(
            org_id, rule_id, current.id, body.is_active
        )
    )


@router.post(
    "/orgs/{org_id}/hours/adjust",
    response_model=AdjustmentResponse,
    status_code=201,
)
def adjust_hours(
    org_id: UUID,
    body: AdjustHoursBody,
    current: CurrentUser = Depends(get_current_user),
    service: RuleService = Depends(get_rule_service),
) -> AdjustmentResponse:
    """Audit + queue an 'adjustment' ledger entry for approval."""
    row: HourAdjustment = service.adjust(
        org_id, current.id, body.student_id, body.activity_id,
        body.delta_hours, body.reason,
    )
    return AdjustmentResponse(
        adjustment_id=row.adjustment_id,
        student_id=row.student_id,
        activity_id=row.activity_id,
        delta_hours=row.delta_hours,
        reason=row.reason,
        created_by=row.created_by,
        created_at=row.created_at,
    )
