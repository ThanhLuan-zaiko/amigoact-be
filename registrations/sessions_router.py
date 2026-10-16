"""HTTP layer for QR attendance sessions and student scans."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, status

from core.dependencies import CurrentUser, get_current_user
from core.dependencies_registrations import get_session_service
from registrations.schemas import (
    AttendanceResponse,
    ScanBody,
    ScanLogResponse,
    SessionBody,
    SessionResponse,
)

if TYPE_CHECKING:
    from registrations.model import AttendanceRecord, AttendanceSession
    from registrations.session_service import SessionService

router = APIRouter(tags=["attendance"])


def _session(row: AttendanceSession) -> SessionResponse:
    return SessionResponse(
        session_id=row.session_id,
        schedule_id=row.schedule_id,
        title=row.title,
        qr_code=row.qr_code,
        opens_at=row.opens_at,
        closes_at=row.closes_at,
        status=row.status,
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


@router.post(
    "/activities/{activity_id}/schedules/{schedule_id}/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    activity_id: UUID,
    schedule_id: UUID,
    body: SessionBody,
    current: CurrentUser = Depends(get_current_user),
    service: SessionService = Depends(get_session_service),
) -> SessionResponse:
    """Manager mints a check-in session plus its QR code."""
    return _session(
        service.create_session(
            activity_id, schedule_id, current.id,
            body.title, body.opens_at, body.closes_at, body.max_uses,
        )
    )


@router.get(
    "/activities/{activity_id}/sessions",
    response_model=list[SessionResponse],
)
def list_sessions(
    activity_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: SessionService = Depends(get_session_service),
) -> list[SessionResponse]:
    """Manager feed of every session across the activity."""
    return [
        _session(s)
        for s in service.list_sessions(activity_id, current.id)
    ]


@router.post(
    "/activities/{activity_id}/schedules/{schedule_id}/sessions/{session_id}/{action}",
    response_model=SessionResponse,
)
def transition_session(
    activity_id: UUID,
    schedule_id: UUID,
    session_id: UUID,
    action: str,
    current: CurrentUser = Depends(get_current_user),
    service: SessionService = Depends(get_session_service),
) -> SessionResponse:
    """open or close a session; closing disables its code."""
    if action not in {"open", "closed"}:
        from core.exceptions import NotFoundError

        raise NotFoundError("Unknown session action.")
    return _session(
        service.set_status(
            activity_id, schedule_id, session_id, current.id, action
        )
    )


@router.get(
    "/activities/{activity_id}/sessions/{session_id}/scans",
    response_model=list[ScanLogResponse],
)
def list_scans(
    activity_id: UUID,
    session_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: SessionService = Depends(get_session_service),
) -> list[ScanLogResponse]:
    """Manager audit feed of scan attempts on one session."""
    return [
        ScanLogResponse(
            scanned_at=row.scanned_at,
            student_id=row.student_id,
            result=row.result,
            device_info=row.device_info,
        )
        for row in service.scan_log(activity_id, session_id, current.id)
    ]


@router.post(
    "/attendance/scan",
    response_model=AttendanceResponse,
    status_code=status.HTTP_201_CREATED,
)
def scan_code(
    body: ScanBody,
    current: CurrentUser = Depends(get_current_user),
    service: SessionService = Depends(get_session_service),
) -> AttendanceResponse:
    """Student scans a session code; every attempt is logged."""
    return _attendance(
        service.scan(body.code, current.id, body.device_info)
    )
