"""Read queries shared by the activity modules."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from src.activities.rules import (
    ACTIVE_REGISTRATION,
    HOLDS_SEAT,
    WAITLISTED,
    requires_approval,
)
from src.activities.schemas import (
    ActivitySummary,
    ShiftResponse,
    ViewerRegistration,
)
from src.models.activities import (
    Activity,
    ActivitySchedule,
    ActivitySlot,
    Registration,
)
from src.models.organizations import Organization


def _seats_taken() -> Any:
    return (
        select(func.count())
        .select_from(Registration)
        .where(
            Registration.activity_id == Activity.id,
            Registration.status.in_(HOLDS_SEAT),
        )
        .correlate(Activity)
        .scalar_subquery()
    )


def _shift_capacity() -> Any:
    return (
        select(func.sum(ActivitySlot.capacity))
        .join(ActivitySchedule, ActivitySchedule.id == ActivitySlot.schedule_id)
        .where(ActivitySchedule.activity_id == Activity.id)
        .correlate(Activity)
        .scalar_subquery()
    )


def summary_query() -> Select[Any]:
    """Live activities of live organizations, with what every summary shows."""
    return (
        select(
            Activity,
            Organization.name,
            Organization.slug,
            _seats_taken(),
            _shift_capacity(),
        )
        .join(Organization, Organization.id == Activity.org_id)
        .where(
            Activity.deleted_at.is_(None),
            Organization.deleted_at.is_(None),
            Organization.status == "active",
        )
    )


def to_summary(row: Sequence[Any]) -> ActivitySummary:
    activity, org_name, org_slug, seats, shift_capacity = row
    hours = activity.hours_awarded
    return ActivitySummary(
        id=activity.id,
        title=activity.title,
        status=activity.status,
        start_at=activity.start_at,
        end_at=activity.end_at,
        registration_deadline=activity.registration_deadline,
        location=activity.location,
        city=activity.city,
        is_remote=activity.is_remote,
        hours_awarded=float(hours) if hours is not None else None,
        requires_approval=requires_approval(activity.requirements_json),
        capacity=(
            int(shift_capacity)
            if shift_capacity is not None
            else activity.max_participants
        ),
        seats_taken=seats,
        organization_name=org_name,
        organization_slug=org_slug,
    )


def _in_scope(activity_id: uuid.UUID, slot_id: uuid.UUID | None) -> tuple[Any, ...]:
    return (
        Registration.activity_id == activity_id,
        Registration.slot_id == slot_id
        if slot_id is not None
        else Registration.slot_id.is_(None),
    )


def held_seats(db: Session, activity_id: uuid.UUID, slot_id: uuid.UUID | None) -> int:
    """Count seats in one shift, or in the activity itself when slot_id is None."""
    return (
        db.scalar(
            select(func.count())
            .select_from(Registration)
            .where(
                *_in_scope(activity_id, slot_id),
                Registration.status.in_(HOLDS_SEAT),
            )
        )
        or 0
    )


def waitlist_size(db: Session, activity_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Registration)
            .where(
                Registration.activity_id == activity_id,
                Registration.status == WAITLISTED,
            )
        )
        or 0
    )


def waitlist_position(db: Session, registration: Registration) -> int | None:
    """Return the 1-based place in the queue, or None when not waiting."""
    if registration.status != WAITLISTED:
        return None
    ahead = db.scalar(
        select(func.count())
        .select_from(Registration)
        .where(
            *_in_scope(registration.activity_id, registration.slot_id),
            Registration.status == WAITLISTED,
            Registration.registered_at < registration.registered_at,
        )
    )
    return (ahead or 0) + 1


def activity_shifts(db: Session, activity_id: uuid.UUID) -> list[ShiftResponse]:
    rows = db.execute(
        select(ActivitySlot)
        .join(ActivitySchedule, ActivitySchedule.id == ActivitySlot.schedule_id)
        .where(ActivitySchedule.activity_id == activity_id)
        .order_by(ActivitySlot.start_at, ActivitySlot.slot_id)
    ).scalars()
    return [
        ShiftResponse(
            id=slot.slot_id,
            title=slot.title,
            start_at=slot.start_at,
            end_at=slot.end_at,
            capacity=slot.capacity,
            seats_taken=held_seats(db, activity_id, slot.slot_id),
        )
        for slot in rows.all()
    ]


def viewer_registrations(
    db: Session, activity_id: uuid.UUID, user_id: uuid.UUID | None
) -> list[ViewerRegistration]:
    """Return the caller's registrations that still count, plus a rejection to explain."""
    if user_id is None:
        return []
    registrations = db.scalars(
        select(Registration).where(
            Registration.activity_id == activity_id,
            Registration.student_id == user_id,
            Registration.status.in_((*ACTIVE_REGISTRATION, "rejected", "attended")),
        )
    ).all()
    return [
        ViewerRegistration(
            id=registration.registration_id,
            shift_id=registration.slot_id,
            status=registration.status,
            review_note=registration.review_note,
            waitlist_position=waitlist_position(db, registration),
        )
        for registration in registrations
    ]
