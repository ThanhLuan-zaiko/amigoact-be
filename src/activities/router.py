"""Routes for activities, their shifts, and registrations."""

from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from src.activities import registration_lists, registrations, service, shifts
from src.activities.schemas import (
    ActivityCreateRequest,
    ActivityDetail,
    ActivityPage,
    ActivityUpdateRequest,
    MyRegistration,
    RegisterRequest,
    RegistrationPage,
    RegistrationResult,
    RegistrationStatus,
    ReviewRequest,
    ShiftRequest,
    ShiftResponse,
)
from src.attendance import hours
from src.attendance.sessions import close_all_sessions
from src.auth.deps import CurrentPrincipal, Db, OptionalPrincipal
from src.organizations.access import require_manager
from src.organizations.service import load_organization
from src.validation import Uuid7

router = APIRouter(tags=["activities"])

Slug = Annotated[str, Path(pattern=r"^[A-Za-z0-9-]{1,80}$")]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=100_000)]
# The pattern rejects control characters. PostgreSQL does not accept NUL in text.
SearchText = Annotated[
    str | None, Query(max_length=100, pattern=r"^[^\x00-\x1f\x7f]*$")
]


@router.get("/activities")
def list_activities(
    db: Db,
    q: SearchText = None,
    city: SearchText = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> ActivityPage:
    return service.list_public_activities(db, q, city, limit, offset)


@router.get("/organizations/{slug}/activities")
def list_organization_activities(
    slug: Slug,
    db: Db,
    principal: OptionalPrincipal,
    limit: Limit = 20,
    offset: Offset = 0,
) -> ActivityPage:
    org = load_organization(db, slug)
    user_id = principal.user.id if principal else None
    return service.list_organization_activities(db, org, user_id, limit, offset)


@router.post("/organizations/{slug}/activities", status_code=status.HTTP_201_CREATED)
def create_activity(
    slug: Slug,
    payload: ActivityCreateRequest,
    principal: CurrentPrincipal,
    db: Db,
) -> ActivityDetail:
    user_id = principal.user.id
    org = load_organization(db, slug)
    require_manager(db, org, user_id)
    activity = service.create_activity(db, org.id, user_id, payload)
    return service.activity_detail(db, activity, user_id)


@router.get("/activities/{activity_id}")
def get_activity(
    activity_id: Uuid7, db: Db, principal: OptionalPrincipal
) -> ActivityDetail:
    activity = service.load_activity(db, activity_id)
    return service.activity_detail(
        db, activity, principal.user.id if principal else None
    )


@router.patch("/activities/{activity_id}")
def update_activity(
    activity_id: Uuid7,
    payload: ActivityUpdateRequest,
    principal: CurrentPrincipal,
    db: Db,
) -> ActivityDetail:
    user_id = principal.user.id
    activity = service.load_activity(db, activity_id, lock=True)
    service.require_activity_manager(db, activity, user_id)
    service.update_activity(db, activity, payload)
    if "max_participants" in payload.model_fields_set:
        registrations.promote_waitlist(db, activity, None, user_id)
    db.commit()
    return service.activity_detail(db, activity, user_id)


@router.delete("/activities/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_activity(activity_id: Uuid7, principal: CurrentPrincipal, db: Db) -> None:
    activity = service.load_activity(db, activity_id, lock=True)
    service.require_activity_manager(db, activity, principal.user.id)
    service.delete_draft(db, activity)


@router.post("/activities/{activity_id}/publish")
def publish_activity(
    activity_id: Uuid7, principal: CurrentPrincipal, db: Db
) -> ActivityDetail:
    user_id = principal.user.id
    activity = service.load_activity(db, activity_id, lock=True)
    service.require_activity_manager(db, activity, user_id)
    service.publish_activity(db, activity)
    return service.activity_detail(db, activity, user_id)


@router.post("/activities/{activity_id}/complete")
def complete_activity(
    activity_id: Uuid7, principal: CurrentPrincipal, db: Db
) -> ActivityDetail:
    user_id = principal.user.id
    activity = service.load_activity(db, activity_id, lock=True)
    service.require_activity_manager(db, activity, user_id)
    service.require_completable(activity)
    hours.award_for_completion(db, activity, user_id)
    service.complete_activity(db, activity)
    return service.activity_detail(db, activity, user_id)


@router.post("/activities/{activity_id}/cancel")
def cancel_activity(
    activity_id: Uuid7, principal: CurrentPrincipal, db: Db
) -> ActivityDetail:
    user_id = principal.user.id
    activity = service.load_activity(db, activity_id, lock=True)
    service.require_activity_manager(db, activity, user_id)
    close_all_sessions(db, activity.id)
    service.cancel_activity(db, activity, user_id)
    return service.activity_detail(db, activity, user_id)


@router.post("/activities/{activity_id}/shifts", status_code=status.HTTP_201_CREATED)
def create_shift(
    activity_id: Uuid7,
    payload: ShiftRequest,
    principal: CurrentPrincipal,
    db: Db,
) -> ShiftResponse:
    activity = service.load_activity(db, activity_id, lock=True)
    service.require_activity_manager(db, activity, principal.user.id)
    return shifts.create_shift(db, activity, payload)


@router.put("/activities/{activity_id}/shifts/{shift_id}")
def update_shift(
    activity_id: Uuid7,
    shift_id: Uuid7,
    payload: ShiftRequest,
    principal: CurrentPrincipal,
    db: Db,
) -> ShiftResponse:
    activity = service.load_activity(db, activity_id, lock=True)
    service.require_activity_manager(db, activity, principal.user.id)
    return shifts.update_shift(db, activity, shift_id, payload)


@router.delete(
    "/activities/{activity_id}/shifts/{shift_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_shift(
    activity_id: Uuid7,
    shift_id: Uuid7,
    principal: CurrentPrincipal,
    db: Db,
) -> None:
    activity = service.load_activity(db, activity_id, lock=True)
    service.require_activity_manager(db, activity, principal.user.id)
    shifts.delete_shift(db, activity, shift_id)


@router.post(
    "/activities/{activity_id}/registrations",
    status_code=status.HTTP_201_CREATED,
)
def register_for_activity(
    activity_id: Uuid7,
    payload: RegisterRequest,
    principal: CurrentPrincipal,
    db: Db,
) -> RegistrationResult:
    return registrations.register(
        db, activity_id, principal.user.id, payload.shift_id, payload.note
    )


@router.get("/activities/{activity_id}/registrations")
def list_activity_registrations(
    activity_id: Uuid7,
    principal: CurrentPrincipal,
    db: Db,
    registration_status: Annotated[
        RegistrationStatus | None, Query(alias="status")
    ] = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> RegistrationPage:
    activity = service.load_activity(db, activity_id)
    service.require_activity_manager(db, activity, principal.user.id)
    return registration_lists.list_activity_registrations(
        db, activity.id, registration_status, limit, offset
    )


@router.get("/registrations/mine")
def list_my_registrations(principal: CurrentPrincipal, db: Db) -> list[MyRegistration]:
    return registration_lists.list_my_registrations(db, principal.user.id)


@router.delete(
    "/registrations/{registration_id}", status_code=status.HTTP_204_NO_CONTENT
)
def cancel_registration(
    registration_id: Uuid7, principal: CurrentPrincipal, db: Db
) -> None:
    activity_id = registrations.activity_id_of(db, registration_id)
    activity = service.load_activity(db, activity_id, lock=True)
    registrations.cancel_registration(db, activity, registration_id, principal.user.id)


@router.post(
    "/registrations/{registration_id}/approve",
    status_code=status.HTTP_204_NO_CONTENT,
)
def approve_registration(
    registration_id: Uuid7,
    payload: ReviewRequest,
    principal: CurrentPrincipal,
    db: Db,
) -> None:
    activity_id = registrations.activity_id_of(db, registration_id)
    activity = service.load_activity(db, activity_id, lock=True)
    service.require_activity_manager(db, activity, principal.user.id)
    registrations.approve_registration(
        db, registration_id, principal.user.id, payload.note
    )


@router.post(
    "/registrations/{registration_id}/reject",
    status_code=status.HTTP_204_NO_CONTENT,
)
def reject_registration(
    registration_id: Uuid7,
    payload: ReviewRequest,
    principal: CurrentPrincipal,
    db: Db,
) -> None:
    activity_id = registrations.activity_id_of(db, registration_id)
    activity = service.load_activity(db, activity_id, lock=True)
    service.require_activity_manager(db, activity, principal.user.id)
    registrations.reject_registration(
        db, activity, registration_id, principal.user.id, payload.note
    )
