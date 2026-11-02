"""Shifts of an activity.

The API shows one shift. The database stores it as one activity_schedules row with
one activity_slots row, so attendance can attach to the schedule later.
"""

import uuid

from fastapi import status
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from src.activities.queries import activity_shifts, held_seats
from src.activities.registrations import promote_waitlist, sync_slot_count
from src.activities.rules import EDITABLE_STATUSES, shift_errors
from src.activities.schemas import ShiftRequest, ShiftResponse
from src.auth.errors import api_error
from src.models.activities import (
    Activity,
    ActivitySchedule,
    ActivitySlot,
    Registration,
)
from src.validation import validation_failure


def _require_editable(activity: Activity) -> None:
    if activity.status not in EDITABLE_STATUSES:
        raise api_error(status.HTTP_409_CONFLICT, "activity_not_editable")


def _check_times(activity: Activity, payload: ShiftRequest) -> None:
    errors = shift_errors(
        start_at=payload.start_at,
        end_at=payload.end_at,
        activity_start=activity.start_at,
        activity_end=activity.end_at,
    )
    if errors:
        raise validation_failure(errors)


def load_shift(
    db: Session, activity_id: uuid.UUID, shift_id: uuid.UUID
) -> tuple[ActivitySlot, ActivitySchedule]:
    row = db.execute(
        select(ActivitySlot, ActivitySchedule)
        .join(ActivitySchedule, ActivitySchedule.id == ActivitySlot.schedule_id)
        .where(
            ActivitySlot.slot_id == shift_id,
            ActivitySchedule.activity_id == activity_id,
        )
    ).first()
    if row is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "shift_not_found")
    return row[0], row[1]


def _response(db: Session, activity_id: uuid.UUID, slot_id: uuid.UUID) -> ShiftResponse:
    return next(
        shift for shift in activity_shifts(db, activity_id) if shift.id == slot_id
    )


def create_shift(
    db: Session, activity: Activity, payload: ShiftRequest
) -> ShiftResponse:
    _require_editable(activity)
    _check_times(activity, payload)
    # Whole-activity registrations would have no shift to belong to.
    has_plain_registrations = db.scalar(
        select(
            exists().where(
                Registration.activity_id == activity.id,
                Registration.slot_id.is_(None),
            )
        )
    )
    if has_plain_registrations:
        raise api_error(status.HTTP_409_CONFLICT, "activity_has_registrations")
    schedule = ActivitySchedule(
        id=uuid.uuid7(),
        activity_id=activity.id,
        title=payload.title,
        start_at=payload.start_at,
        end_at=payload.end_at,
    )
    db.add(schedule)
    db.flush()
    slot = ActivitySlot(
        slot_id=uuid.uuid7(),
        schedule_id=schedule.id,
        title=payload.title,
        capacity=payload.capacity,
        start_at=payload.start_at,
        end_at=payload.end_at,
    )
    db.add(slot)
    db.commit()
    return _response(db, activity.id, slot.slot_id)


def update_shift(
    db: Session, activity: Activity, shift_id: uuid.UUID, payload: ShiftRequest
) -> ShiftResponse:
    _require_editable(activity)
    _check_times(activity, payload)
    slot, schedule = load_shift(db, activity.id, shift_id)
    if payload.capacity < held_seats(db, activity.id, shift_id):
        raise validation_failure({"capacity": "capacity_below_registered"})
    for row in (slot, schedule):
        row.title = payload.title
        row.start_at = payload.start_at
        row.end_at = payload.end_at
    slot.capacity = payload.capacity
    db.flush()
    promote_waitlist(db, activity, shift_id, actor_id=None)
    sync_slot_count(db, activity.id, shift_id)
    db.commit()
    return _response(db, activity.id, shift_id)


def delete_shift(db: Session, activity: Activity, shift_id: uuid.UUID) -> None:
    """A shift with any registration stays, so its history is never lost."""
    _require_editable(activity)
    _, schedule = load_shift(db, activity.id, shift_id)
    has_registrations = db.scalar(
        select(exists().where(Registration.slot_id == shift_id))
    )
    if has_registrations:
        raise api_error(status.HTTP_409_CONFLICT, "shift_has_registrations")
    db.delete(schedule)
    db.commit()
