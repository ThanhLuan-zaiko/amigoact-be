"""Creating, finding, editing, and closing activities."""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from src.activities.queries import (
    activity_shifts,
    held_seats,
    summary_query,
    to_summary,
    viewer_registrations,
    waitlist_size,
)
from src.activities.rules import (
    ACTIVE_REGISTRATION,
    CANCELLED,
    COMPLETED,
    DRAFT,
    EDITABLE_STATUSES,
    PUBLISHED,
    can_cancel_registration,
    publish_errors,
    registration_is_open,
    schedule_errors,
)
from src.activities.schemas import (
    ActivityCreateRequest,
    ActivityDetail,
    ActivityPage,
    ActivityUpdateRequest,
    ActivityViewer,
)
from src.auth.errors import api_error
from src.auth.rate_limit import enforce_rate_limit
from src.models.activities import (
    Activity,
    ActivitySchedule,
    ActivitySlot,
    Registration,
    RegistrationStatusHistory,
)
from src.models.organizations import Organization
from src.notifications.events import activity_data, notify
from src.organizations.access import get_access
from src.pagination import count_rows
from src.validation import validation_failure

CREATE_LIMIT = 30

CREATE_WINDOW = 60 * 60


def load_activity(
    db: Session, activity_id: uuid.UUID, *, lock: bool = False
) -> Activity:
    """Find a live activity. The lock makes seat changes on it run one at a time."""

    query = (
        select(Activity)
        .join(Organization, Organization.id == Activity.org_id)
        .where(
            Activity.id == activity_id,
            Activity.deleted_at.is_(None),
            Organization.deleted_at.is_(None),
            Organization.status == "active",
        )
    )

    if lock:
        query = query.with_for_update(of=Activity)
    activity = db.scalar(query)
    if activity is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "activity_not_found")
    return activity


def require_activity_manager(
    db: Session, activity: Activity, user_id: uuid.UUID
) -> None:
    org = db.get(Organization, activity.org_id)
    if org is None or not get_access(db, org, user_id).can_manage:
        raise api_error(status.HTTP_403_FORBIDDEN, "organization_forbidden")


def _can_manage(db: Session, activity: Activity, user_id: uuid.UUID | None) -> bool:
    org = db.get(Organization, activity.org_id)
    if user_id is None or org is None:
        return False
    return get_access(db, org, user_id).can_manage


def activity_detail(
    db: Session, activity: Activity, user_id: uuid.UUID | None
) -> ActivityDetail:
    """Drafts stay hidden from everyone except the organization's managers."""
    can_manage = _can_manage(db, activity, user_id)
    if activity.status == DRAFT and not can_manage:
        raise api_error(status.HTTP_404_NOT_FOUND, "activity_not_found")
    now = datetime.now(UTC)
    summary = to_summary(
        db.execute(summary_query().where(Activity.id == activity.id)).one()
    )

    return ActivityDetail(
        **summary.model_dump(),
        description=activity.description,
        address=activity.address,
        max_participants=activity.max_participants,
        published_at=activity.published_at,
        waitlist_count=waitlist_size(db, activity.id),
        registration_open=registration_is_open(
            status=activity.status,
            start_at=activity.start_at,
            deadline=activity.registration_deadline,
            now=now,
        ),
        can_cancel_registration=can_cancel_registration(
            status=activity.status, start_at=activity.start_at, now=now
        ),
        shifts=activity_shifts(db, activity.id),
        viewer=ActivityViewer(
            can_manage=can_manage,
            registrations=viewer_registrations(db, activity.id, user_id),
        ),
    )


def create_activity(
    db: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: ActivityCreateRequest,
) -> Activity:
    """Create a draft. Nothing is checked for completeness until it is published."""

    errors = schedule_errors(
        payload.start_at, payload.end_at, payload.registration_deadline
    )

    if errors:
        raise validation_failure(errors)
    enforce_rate_limit(db, f"activity-create:{user_id}", CREATE_LIMIT, CREATE_WINDOW)
    activity = Activity(
        id=uuid.uuid7(),
        org_id=org_id,
        created_by=user_id,
        status=DRAFT,
        requirements_json={"requires_approval": payload.requires_approval},
        **payload.model_dump(exclude={"requires_approval"}),
    )
    db.add(activity)
    db.commit()
    return activity


def _check_shifts_still_fit(db: Session, activity: Activity) -> None:
    rows = db.execute(
        select(ActivitySchedule.start_at, ActivitySchedule.end_at).where(
            ActivitySchedule.activity_id == activity.id
        )
    ).all()

    for start_at, end_at in rows:
        if activity.start_at and start_at and start_at < activity.start_at:
            raise validation_failure({"start_at": "activity_time_excludes_shift"})

        if activity.end_at and end_at and end_at > activity.end_at:
            raise validation_failure({"end_at": "activity_time_excludes_shift"})


def _apply_update(activity: Activity, payload: ActivityUpdateRequest) -> None:
    for field in payload.model_fields_set - {"requires_approval"}:
        setattr(activity, field, getattr(payload, field))

    if "requires_approval" in payload.model_fields_set:
        activity.requirements_json = {
            **(activity.requirements_json or {}),
            "requires_approval": payload.requires_approval,
        }


def update_activity(
    db: Session, activity: Activity, payload: ActivityUpdateRequest
) -> None:
    """Check the merged result, because a rule can span sent and stored fields."""

    if activity.status not in EDITABLE_STATUSES:
        raise api_error(status.HTTP_409_CONFLICT, "activity_not_editable")
    was_published = activity.status == PUBLISHED
    old_start = activity.start_at
    with db.no_autoflush:
        _apply_update(activity, payload)

        errors = schedule_errors(
            activity.start_at, activity.end_at, activity.registration_deadline
        )

        if was_published:
            errors = publish_errors(
                start_at=activity.start_at,
                end_at=activity.end_at,
                deadline=activity.registration_deadline,
                location=activity.location,
                is_remote=activity.is_remote,
                now=datetime.now(UTC),
            )
            # A running activity can still be edited if its start stays the same.
            if activity.start_at == old_start and errors.get("start_at") == (
                "start_in_past"
            ):
                del errors["start_at"]

            if errors.get("registration_deadline") == "deadline_in_past":
                del errors["registration_deadline"]

        if errors:
            raise validation_failure(errors)
        _check_shifts_still_fit(db, activity)
        if "max_participants" in payload.model_fields_set:
            _check_capacity_covers_seats(db, activity)


def _check_capacity_covers_seats(db: Session, activity: Activity) -> None:
    limit = activity.max_participants
    if limit is not None and limit < held_seats(db, activity.id, None):
        raise validation_failure({"max_participants": "capacity_below_registered"})


def require_completable(activity: Activity) -> None:
    if activity.status != PUBLISHED:
        raise api_error(status.HTTP_409_CONFLICT, "activity_not_editable")

    if activity.start_at is None or activity.start_at > datetime.now(UTC):
        raise api_error(status.HTTP_409_CONFLICT, "activity_not_started")


def complete_activity(db: Session, activity: Activity) -> None:
    activity.status = COMPLETED
    db.commit()


def cancel_activity(db: Session, activity: Activity, actor_id: uuid.UUID) -> None:
    """Cancel the activity and every registration that was still active."""

    if activity.status != PUBLISHED:
        raise api_error(status.HTTP_409_CONFLICT, "activity_not_editable")
    now = datetime.now(UTC)
    activity.status = CANCELLED
    registrations = db.scalars(
        select(Registration).where(
            Registration.activity_id == activity.id,
            Registration.status.in_(ACTIVE_REGISTRATION),
        )
    ).all()

    for registration in registrations:
        db.add(
            RegistrationStatusHistory(
                history_id=uuid.uuid7(),
                registration_id=registration.registration_id,
                from_status=registration.status,
                to_status=CANCELLED,
                changed_by=actor_id,
                note="activity_cancelled",
            )
        )
        registration.status = CANCELLED
        registration.cancelled_at = now
    # Someone with several shifts hears about the cancellation once.
    data = activity_data(db, activity.id)
    for student_id in {registration.student_id for registration in registrations}:
        notify(db, student_id, "activity_cancelled", data)

    slot_ids = (
        select(ActivitySlot.slot_id)
        .join(ActivitySchedule, ActivitySchedule.id == ActivitySlot.schedule_id)
        .where(ActivitySchedule.activity_id == activity.id)
    )

    for slot in db.scalars(
        select(ActivitySlot).where(ActivitySlot.slot_id.in_(slot_ids))
    ):
        slot.registered = 0
    db.commit()


def delete_draft(db: Session, activity: Activity) -> None:
    """Only a draft can go away. A published activity is cancelled, which keeps its history."""

    if activity.status != DRAFT:
        raise api_error(status.HTTP_409_CONFLICT, "activity_not_draft")
    activity.deleted_at = datetime.now(UTC)
    db.commit()


def _page(db: Session, query: Select[Any], limit: int, offset: int) -> ActivityPage:
    rows = db.execute(query.limit(limit + 1).offset(offset)).all()
    return ActivityPage(
        items=[to_summary(row) for row in rows[:limit]],
        next_offset=offset + limit if len(rows) > limit else None,
        total=count_rows(db, query),
    )


def list_public_activities(
    db: Session,
    search: str | None,
    city: str | None,
    limit: int,
    offset: int,
) -> ActivityPage:
    """Published activities that have not started, soonest first."""

    query = summary_query().where(
        Activity.status == PUBLISHED, Activity.start_at > func.now()
    )

    if search:
        query = query.where(Activity.title.icontains(search, autoescape=True))

    if city:
        query = query.where(Activity.city.icontains(city, autoescape=True))
    query = query.order_by(Activity.start_at, Activity.id)
    return _page(db, query, limit, offset)


def list_organization_activities(
    db: Session,
    org: Organization,
    user_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> ActivityPage:
    """Managers also see drafts here. Everyone else sees what was published."""
    can_manage = user_id is not None and get_access(db, org, user_id).can_manage
    query = summary_query().where(Activity.org_id == org.id)
    if not can_manage:
        query = query.where(Activity.status != DRAFT)
    query = query.order_by(Activity.start_at.desc().nulls_first(), Activity.id.desc())
    return _page(db, query, limit, offset)
