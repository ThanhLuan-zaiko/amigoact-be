"""HTTP layer for registrations and attendance."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends

from core.dependencies import CurrentUser, get_current_user
from core.dependencies_features import (
    get_attendance_service,
    get_registration_service,
)
from registrations.schemas import (
    ApplyBody,
    AttendanceResponse,
    CheckinBody,
    CheckoutBody,
    RegistrationResponse,
    ReviewBody,
    RosterResponse,
    TicketResponse,
)

if TYPE_CHECKING:
    from registrations.attendance_service import AttendanceService
    from registrations.model import AttendanceRecord, Registration
    from registrations.service import RegistrationService, RosterItem

router = APIRouter(tags=["registrations"])


def _response(row: Registration) -> RegistrationResponse:
    return RegistrationResponse(
        registration_id=row.registration_id,
        activity_id=row.activity_id,
        student_id=row.student_id,
        status=row.status,
        note=row.note,
        review_note=row.review_note,
        registered_at=row.registered_at,
        reviewed_at=row.reviewed_at,
        cancelled_at=row.cancelled_at,
    )


def _attendance(row: AttendanceRecord) -> AttendanceResponse:
    return AttendanceResponse(
        record_id=row.record_id,
        activity_id=row.activity_id,
        student_id=row.student_id,
        session_id=row.session_id,
        method=row.method,
        scanned_at=row.scanned_at,
        checked_out_at=row.checked_out_at,
        check_out_method=row.check_out_method,
        actual_hours=row.actual_hours,
    )


def _roster(item: RosterItem) -> RosterResponse:
    return RosterResponse(
        registration_id=item.registration_id,
        student_id=item.student_id,
        student_name=item.student_name,
        student_email=item.student_email,
        status=item.status,
        note=item.note,
        review_note=item.review_note,
        registered_at=item.registered_at,  # type: ignore[arg-type]
    )


@router.post(
    "/activities/{activity_id}/registrations",
    response_model=RegistrationResponse,
    status_code=201,
)
def apply(
    activity_id: UUID,
    body: ApplyBody,
    current: CurrentUser = Depends(get_current_user),
    service: RegistrationService = Depends(get_registration_service),
) -> RegistrationResponse:
    """Apply to a published activity; duplicates hit the guard."""
    return _response(
        service.apply(activity_id, current.id, body.note)
    )


@router.get(
    "/registrations/mine", response_model=list[RegistrationResponse]
)
def my_registrations(
    current: CurrentUser = Depends(get_current_user),
    service: RegistrationService = Depends(get_registration_service),
) -> list[RegistrationResponse]:
    """The caller's application history across activities."""
    return [_response(row) for row in service.list_mine(current.id)]


@router.get(
    "/activities/{activity_id}/registrations",
    response_model=list[RosterResponse],
)
def activity_roster(
    activity_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: RegistrationService = Depends(get_registration_service),
) -> list[RosterResponse]:
    """Manager roster with applicant names and statuses."""
    return [
        _roster(item)
        for item in service.list_for_activity(activity_id, current.id)
    ]


@router.post(
    "/activities/{activity_id}/registrations/{registration_id}/review",
    response_model=RegistrationResponse,
)
def review(
    activity_id: UUID,
    registration_id: UUID,
    body: ReviewBody,
    current: CurrentUser = Depends(get_current_user),
    service: RegistrationService = Depends(get_registration_service),
) -> RegistrationResponse:
    """Approve, reject, or waitlist one pending application."""
    return _response(
        service.review(
            activity_id, registration_id, current.id,
            body.status, body.review_note,
        )
    )


@router.post(
    "/activities/{activity_id}/registrations/{registration_id}/cancel",
    response_model=RegistrationResponse,
)
def cancel(
    activity_id: UUID,
    registration_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: RegistrationService = Depends(get_registration_service),
) -> RegistrationResponse:
    """Applicant withdraws a live application."""
    return _response(
        service.cancel(activity_id, registration_id, current.id)
    )


@router.get(
    "/activities/{activity_id}/registrations/{registration_id}/ticket",
    response_model=TicketResponse,
)
def ticket(
    activity_id: UUID,
    registration_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: RegistrationService = Depends(get_registration_service),
) -> TicketResponse:
    """Personal QR payload for the applicant's device."""
    row = service.my_ticket(activity_id, registration_id, current.id)
    return TicketResponse(
        registration_id=row.registration_id,
        checkin_token=row.checkin_token,
        activity_id=row.activity_id,
        status=row.status,
    )


@router.post(
    "/activities/{activity_id}/checkin",
    response_model=AttendanceResponse,
    status_code=201,
)
def check_in(
    activity_id: UUID,
    body: CheckinBody,
    current: CurrentUser = Depends(get_current_user),
    service: AttendanceService = Depends(get_attendance_service),
) -> AttendanceResponse:
    """Staff scans a personal check-in token."""
    return _attendance(
        service.check_in(activity_id, body.checkin_token, current.id)
    )


@router.post(
    "/activities/{activity_id}/registrations/{registration_id}/checkin",
    response_model=AttendanceResponse,
    status_code=201,
)
def check_in_manual(
    activity_id: UUID,
    registration_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: AttendanceService = Depends(get_attendance_service),
) -> AttendanceResponse:
    """Manager marks a registration present without QR."""
    return _attendance(
        service.check_in_manual(activity_id, registration_id, current.id)
    )


@router.post(
    "/activities/{activity_id}/attendance/{record_id}/checkout",
    response_model=AttendanceResponse,
)
def check_out(
    activity_id: UUID,
    record_id: UUID,
    body: CheckoutBody,
    current: CurrentUser = Depends(get_current_user),
    service: AttendanceService = Depends(get_attendance_service),
) -> AttendanceResponse:
    """Stamp check-out; hours derive from duration unless overridden."""
    return _attendance(
        service.check_out(
            activity_id, record_id, current.id, body.actual_hours
        )
    )


@router.get(
    "/activities/{activity_id}/attendance",
    response_model=list[AttendanceResponse],
)
def list_attendance(
    activity_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: AttendanceService = Depends(get_attendance_service),
) -> list[AttendanceResponse]:
    """Manager feed of every check-in on the activity."""
    return [
        _attendance(row)
        for row in service.list_attendance(activity_id, current.id)
    ]


@router.get(
    "/attendance/mine", response_model=list[AttendanceResponse]
)
def my_attendance(
    current: CurrentUser = Depends(get_current_user),
    service: AttendanceService = Depends(get_attendance_service),
) -> list[AttendanceResponse]:
    """The caller's check-in history across activities."""
    return [_attendance(row) for row in service.my_attendance(current.id)]
