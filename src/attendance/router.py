"""Routes for check-in sessions, attendance, appeals, and volunteer hours."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, status

from src.activities import service as activity_service
from src.attendance import appeals, checkin, hours, records, sessions
from src.attendance.schemas import (
    ActivityHoursEntry,
    AdjustmentRequest,
    AppealApproveRequest,
    AppealRequest,
    AppealResponse,
    CheckInRequest,
    CheckInResult,
    HourRuleRequest,
    HourRuleResponse,
    ManualRecordRequest,
    MyHours,
    RosterEntry,
    SessionCreateRequest,
    SessionResponse,
)
from src.auth.deps import Client, CurrentPrincipal, Db
from src.auth.errors import api_error
from src.models.activities import Registration
from src.notifications.delivery import deliver_emails
from src.organizations.access import require_manager
from src.organizations.service import load_organization
from src.validation import Uuid7

router = APIRouter(tags=["attendance"], dependencies=[Depends(deliver_emails)])

Slug = Annotated[str, Path(pattern=r"^[A-Za-z0-9-]{1,80}$")]
AppealStatus = Literal["pending", "approved", "rejected"]


@router.post(
    "/activities/{activity_id}/attendance-sessions",
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    activity_id: Uuid7,
    payload: SessionCreateRequest,
    principal: CurrentPrincipal,
    db: Db,
) -> SessionResponse:
    activity = activity_service.load_activity(db, activity_id, lock=True)
    activity_service.require_activity_manager(db, activity, principal.user.id)
    return sessions.create_session(db, activity, principal.user.id, payload)


@router.get("/activities/{activity_id}/attendance-sessions")
def list_sessions(
    activity_id: Uuid7, principal: CurrentPrincipal, db: Db
) -> list[SessionResponse]:
    activity = activity_service.load_activity(db, activity_id)
    activity_service.require_activity_manager(db, activity, principal.user.id)
    return sessions.list_sessions(db, activity.id)


@router.post(
    "/attendance-sessions/{session_id}/close",
    status_code=status.HTTP_204_NO_CONTENT,
)
def close_session(session_id: Uuid7, principal: CurrentPrincipal, db: Db) -> None:
    session = sessions.load_session(db, session_id)
    activity = activity_service.load_activity(
        db, sessions.activity_id_of_session(db, session)
    )
    activity_service.require_activity_manager(db, activity, principal.user.id)
    sessions.close_session(db, session)


@router.get("/attendance-sessions/{session_id}/roster")
def session_roster(
    session_id: Uuid7, principal: CurrentPrincipal, db: Db
) -> list[RosterEntry]:
    session = sessions.load_session(db, session_id)
    activity = activity_service.load_activity(
        db, sessions.activity_id_of_session(db, session)
    )
    activity_service.require_activity_manager(db, activity, principal.user.id)
    return records.session_roster(db, activity.id, session)


@router.post(
    "/attendance-sessions/{session_id}/records",
    status_code=status.HTTP_204_NO_CONTENT,
)
def mark_attended(
    session_id: Uuid7,
    payload: ManualRecordRequest,
    principal: CurrentPrincipal,
    db: Db,
) -> None:
    session = sessions.load_session(db, session_id)
    activity = activity_service.load_activity(
        db, sessions.activity_id_of_session(db, session)
    )
    activity_service.require_activity_manager(db, activity, principal.user.id)
    records.mark_attended(
        db, activity, session, payload.registration_id, principal.user.id
    )


@router.post(
    "/attendance-records/{record_id}/verify",
    status_code=status.HTTP_204_NO_CONTENT,
)
def verify_record(record_id: Uuid7, principal: CurrentPrincipal, db: Db) -> None:
    record = records.load_record(db, record_id)
    activity = activity_service.load_activity(db, record.activity_id)
    activity_service.require_activity_manager(db, activity, principal.user.id)
    records.verify_record(db, activity, record, principal.user.id)


@router.delete(
    "/attendance-records/{record_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_record(record_id: Uuid7, principal: CurrentPrincipal, db: Db) -> None:
    record = records.load_record(db, record_id)
    activity = activity_service.load_activity(db, record.activity_id)
    activity_service.require_activity_manager(db, activity, principal.user.id)
    records.delete_record(db, activity, record)


@router.post("/attendance/check-in", status_code=status.HTTP_201_CREATED)
def check_in(
    payload: CheckInRequest,
    principal: CurrentPrincipal,
    db: Db,
    client: Client,
) -> CheckInResult:
    return checkin.check_in(db, principal.user.id, payload, client)


@router.post(
    "/registrations/{registration_id}/appeals",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
def create_appeal(
    registration_id: Uuid7,
    payload: AppealRequest,
    principal: CurrentPrincipal,
    db: Db,
) -> None:
    registration = db.get(Registration, registration_id)
    if registration is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "registration_not_found")
    activity = activity_service.load_activity(db, registration.activity_id)
    appeals.create_appeal(db, activity, registration, principal.user.id, payload.reason)


@router.get("/activities/{activity_id}/appeals")
def list_appeals(
    activity_id: Uuid7,
    principal: CurrentPrincipal,
    db: Db,
    appeal_status: Annotated[AppealStatus | None, Query(alias="status")] = None,
) -> list[AppealResponse]:
    activity = activity_service.load_activity(db, activity_id)
    activity_service.require_activity_manager(db, activity, principal.user.id)
    return appeals.list_appeals(db, activity.id, appeal_status)


@router.post("/appeals/{appeal_id}/approve", status_code=status.HTTP_204_NO_CONTENT)
def approve_appeal(
    appeal_id: Uuid7,
    payload: AppealApproveRequest,
    principal: CurrentPrincipal,
    db: Db,
) -> None:
    appeal = appeals.load_appeal(db, appeal_id)
    activity = activity_service.load_activity(db, appeal.activity_id, lock=True)
    activity_service.require_activity_manager(db, activity, principal.user.id)
    appeals.approve_appeal(
        db, activity, appeal, principal.user.id, payload.registration_id
    )


@router.post("/appeals/{appeal_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
def reject_appeal(appeal_id: Uuid7, principal: CurrentPrincipal, db: Db) -> None:
    appeal = appeals.load_appeal(db, appeal_id)
    activity = activity_service.load_activity(db, appeal.activity_id)
    activity_service.require_activity_manager(db, activity, principal.user.id)
    appeals.reject_appeal(db, appeal, principal.user.id)


@router.get("/hours/mine")
def my_hours(principal: CurrentPrincipal, db: Db) -> MyHours:
    return hours.my_hours(db, principal.user.id)


@router.get("/activities/{activity_id}/hours")
def activity_hours(
    activity_id: Uuid7, principal: CurrentPrincipal, db: Db
) -> list[ActivityHoursEntry]:
    activity = activity_service.load_activity(db, activity_id)
    activity_service.require_activity_manager(db, activity, principal.user.id)
    return hours.activity_hours(db, activity.id)


@router.post(
    "/activities/{activity_id}/hour-adjustments",
    status_code=status.HTTP_204_NO_CONTENT,
)
def adjust_hours(
    activity_id: Uuid7,
    payload: AdjustmentRequest,
    principal: CurrentPrincipal,
    db: Db,
) -> None:
    activity = activity_service.load_activity(db, activity_id, lock=True)
    activity_service.require_activity_manager(db, activity, principal.user.id)
    hours.adjust_hours(db, activity, principal.user.id, payload)


@router.get("/organizations/{slug}/hour-rule")
def get_hour_rule(slug: Slug, principal: CurrentPrincipal, db: Db) -> HourRuleResponse:
    org = load_organization(db, slug)
    require_manager(db, org, principal.user.id)
    return hours.get_hour_rule(db, org.id)


@router.put("/organizations/{slug}/hour-rule")
def set_hour_rule(
    slug: Slug,
    payload: HourRuleRequest,
    principal: CurrentPrincipal,
    db: Db,
) -> HourRuleResponse:
    org = load_organization(db, slug)
    require_manager(db, org, principal.user.id)
    return hours.set_hour_rule(db, org.id, payload)
