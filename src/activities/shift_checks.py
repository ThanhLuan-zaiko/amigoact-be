"""Checks on which shift a volunteer is registering for."""

import uuid

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from src.activities.rules import ACTIVE_REGISTRATION, times_overlap
from src.auth.errors import api_error
from src.models.activities import (
    Activity,
    ActivitySchedule,
    ActivitySlot,
    Registration,
)
from src.validation import validation_failure


def resolve_slot(
    db: Session, activity: Activity, shift_id: uuid.UUID | None
) -> ActivitySlot | None:
    # Joined to the slots, because attendance can add a schedule that is not a shift.
    has_shifts = db.scalar(
        select(ActivitySlot.slot_id)
        .join(ActivitySchedule, ActivitySchedule.id == ActivitySlot.schedule_id)
        .where(ActivitySchedule.activity_id == activity.id)
        .limit(1)
    )
    if has_shifts and shift_id is None:
        raise validation_failure({"shift_id": "shift_required"})
    if shift_id is None:
        return None
    slot = db.scalar(
        select(ActivitySlot)
        .join(ActivitySchedule, ActivitySchedule.id == ActivitySlot.schedule_id)
        .where(
            ActivitySlot.slot_id == shift_id,
            ActivitySchedule.activity_id == activity.id,
        )
    )
    if slot is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "shift_not_found")
    return slot


def reject_overlap(
    db: Session, activity_id: uuid.UUID, user_id: uuid.UUID, slot: ActivitySlot
) -> None:
    """One person cannot be in two shifts of the same activity at the same time."""
    other = aliased(ActivitySlot)
    rows = db.execute(
        select(other.start_at, other.end_at)
        .join(Registration, Registration.slot_id == other.slot_id)
        .where(
            Registration.activity_id == activity_id,
            Registration.student_id == user_id,
            Registration.status.in_(ACTIVE_REGISTRATION),
            other.slot_id != slot.slot_id,
        )
    ).all()
    for start_at, end_at in rows:
        if times_overlap(slot.start_at, slot.end_at, start_at, end_at):
            raise api_error(status.HTTP_409_CONFLICT, "shift_overlap")
