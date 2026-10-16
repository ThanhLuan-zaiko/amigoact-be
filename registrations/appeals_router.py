"""HTTP layer for attendance appeals and per-registration summaries."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, status

from core.dependencies import CurrentUser, get_current_user
from core.dependencies_registrations import (
    get_appeal_service,
    get_session_service,
)
from registrations.schemas import (
    AppealBody,
    AppealResolveBody,
    AppealResponse,
    SummaryResponse,
)

if TYPE_CHECKING:
    from registrations.appeal_service import AppealService
    from registrations.model import AttendanceAppeal, AttendanceSummary
    from registrations.session_service import SessionService

router = APIRouter(tags=["attendance"])


def _appeal(row: AttendanceAppeal) -> AppealResponse:
    return AppealResponse(
        activity_id=row.activity_id,
        student_id=row.student_id,
        appeal_id=row.appeal_id,
        record_id=row.record_id,
        reason=row.reason,
        status=row.status,
        resolved_by=row.resolved_by,
        resolved_at=row.resolved_at,
        created_at=row.created_at,
    )


def _summary(row: AttendanceSummary) -> SummaryResponse:
    return SummaryResponse(
        registration_id=row.registration_id,
        activity_id=row.activity_id,
        student_id=row.student_id,
        sessions_total=row.sessions_total,
        sessions_attended=row.sessions_attended,
        minutes_attended=row.minutes_attended,
        status=row.status,
        updated_at=row.updated_at,
    )


@router.post(
    "/activities/{activity_id}/appeals",
    response_model=AppealResponse,
    status_code=status.HTTP_201_CREATED,
)
def file_appeal(
    activity_id: UUID,
    body: AppealBody,
    current: CurrentUser = Depends(get_current_user),
    service: AppealService = Depends(get_appeal_service),
) -> AppealResponse:
    """Student disputes a missing or wrong attendance record."""
    return _appeal(
        service.file(
            activity_id, current.id, body.reason, body.record_id
        )
    )


@router.get(
    "/activities/{activity_id}/appeals",
    response_model=list[AppealResponse],
)
def list_appeals(
    activity_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: AppealService = Depends(get_appeal_service),
) -> list[AppealResponse]:
    """Manager queue: pending appeals first."""
    return [
        _appeal(a)
        for a in service.list_for_activity(activity_id, current.id)
    ]


@router.get(
    "/activities/{activity_id}/appeals/mine",
    response_model=list[AppealResponse],
)
def my_appeals(
    activity_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: AppealService = Depends(get_appeal_service),
) -> list[AppealResponse]:
    """The caller's own appeal history for one activity."""
    return [
        _appeal(a) for a in service.mine(activity_id, current.id)
    ]


@router.post(
    "/activities/{activity_id}/appeals/{student_id}/{appeal_id}/resolve",
    response_model=AppealResponse,
)
def resolve_appeal(
    activity_id: UUID,
    student_id: UUID,
    appeal_id: UUID,
    body: AppealResolveBody,
    current: CurrentUser = Depends(get_current_user),
    service: AppealService = Depends(get_appeal_service),
) -> AppealResponse:
    """Approve grants a manual check-in; reject stamps the appeal."""
    return _appeal(
        service.resolve(
            activity_id, student_id, appeal_id,
            current.id, body.status,
        )
    )


@router.get(
    "/activities/{activity_id}/registrations/{registration_id}/summary",
    response_model=SummaryResponse,
)
def attendance_summary(
    activity_id: UUID,
    registration_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: SessionService = Depends(get_session_service),
) -> SummaryResponse:
    """Live rollup; students read their own, managers read all."""
    return _summary(
        service.summary(activity_id, registration_id, current.id)
    )
