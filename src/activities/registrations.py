"""Registering for activities, the waitlist, and reviewing registrations.

Every seat change locks the activity row first, so two requests can never take the
last seat together.
"""

import uuid
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from src.activities.queries import held_seats, waitlist_position
from src.activities.rules import (
    ACTIVE_REGISTRATION,
    APPROVED,
    CANCELLED,
    PENDING,
    PUBLISHED,
    REJECTED,
    WAITLISTED,
    admitted_status,
    can_cancel_registration,
    initial_status,
    registration_is_open,
    requires_approval,
    times_overlap,
)
from src.activities.schemas import (
    RegistrationResult,
)
from src.activities.service import load_activity
from src.auth.errors import api_error
from src.auth.rate_limit import enforce_rate_limit
from src.models.activities import (
    Activity,
    ActivitySchedule,
    ActivitySlot,
    Registration,
    RegistrationStatusHistory,
)
from src.validation import validation_failure

REGISTER_LIMIT = 60
REGISTER_WINDOW = 60 * 60


def record_change(
    db: Session,
    registration: Registration,
    new_status: str,
    actor_id: uuid.UUID | None,
    note: str | None = None,
) -> None:
    """Change the status and keep a history row for every change."""
    db.add(
        RegistrationStatusHistory(
            history_id=uuid.uuid7(),
            registration_id=registration.registration_id,
            from_status=registration.status if registration.status else None,
            to_status=new_status,
            changed_by=actor_id,
            note=note,
        )
    )
    registration.status = new_status


def sync_slot_count(
    db: Session, activity_id: uuid.UUID, slot_id: uuid.UUID | None
) -> None:
    if slot_id is None:
        return
    db.flush()
    slot = db.get(ActivitySlot, slot_id)
    if slot is not None:
        slot.registered = held_seats(db, activity_id, slot_id)


def _capacity(db: Session, activity: Activity, slot_id: uuid.UUID | None) -> int | None:
    if slot_id is None:
        return activity.max_participants
    slot = db.get(ActivitySlot, slot_id)
    return slot.capacity if slot else None


def promote_waitlist(
    db: Session,
    activity: Activity,
    slot_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
) -> None:
    """Move the oldest waiting volunteers into any free seats."""
    now = datetime.now(UTC)
    if activity.status != PUBLISHED or (
        activity.start_at is not None and activity.start_at <= now
    ):
        return
    db.flush()
    capacity = _capacity(db, activity, slot_id)
    slot_filter = (
        Registration.slot_id == slot_id
        if slot_id is not None
        else Registration.slot_id.is_(None)
    )
    waiting = db.scalars(
        select(Registration)
        .where(
            Registration.activity_id == activity.id,
            slot_filter,
            Registration.status == WAITLISTED,
        )
        .order_by(Registration.registered_at, Registration.registration_id)
    ).all()
    free = (
        len(waiting)
        if capacity is None
        else capacity - held_seats(db, activity.id, slot_id)
    )
    for registration in waiting[: max(free, 0)]:
        record_change(
            db,
            registration,
            admitted_status(requires_approval(activity.requirements_json)),
            actor_id,
            "promoted_from_waitlist",
        )


def _resolve_slot(
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


def _reject_overlap(
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


def _existing_registration(
    db: Session, activity_id: uuid.UUID, user_id: uuid.UUID, slot_id: uuid.UUID | None
) -> Registration | None:
    return db.scalar(
        select(Registration).where(
            Registration.activity_id == activity_id,
            Registration.student_id == user_id,
            Registration.slot_id == slot_id
            if slot_id is not None
            else Registration.slot_id.is_(None),
        )
    )


def register(
    db: Session,
    activity_id: uuid.UUID,
    user_id: uuid.UUID,
    shift_id: uuid.UUID | None,
    note: str | None,
) -> RegistrationResult:
    enforce_rate_limit(
        db, f"activity-register:{user_id}", REGISTER_LIMIT, REGISTER_WINDOW
    )
    activity = load_activity(db, activity_id, lock=True)
    now = datetime.now(UTC)
    if activity.status != PUBLISHED:
        raise api_error(status.HTTP_409_CONFLICT, "activity_not_open")
    if not registration_is_open(
        status=activity.status,
        start_at=activity.start_at,
        deadline=activity.registration_deadline,
        now=now,
    ):
        raise api_error(status.HTTP_409_CONFLICT, "registration_closed")

    slot = _resolve_slot(db, activity, shift_id)
    slot_id = slot.slot_id if slot else None
    existing = _existing_registration(db, activity.id, user_id, slot_id)
    if existing is not None and existing.status in (*ACTIVE_REGISTRATION, "attended"):
        raise api_error(status.HTTP_409_CONFLICT, "already_registered")
    if existing is not None and existing.status == REJECTED:
        raise api_error(status.HTTP_409_CONFLICT, "registration_rejected")
    if slot is not None:
        _reject_overlap(db, activity.id, user_id, slot)

    new_status = initial_status(
        capacity=slot.capacity if slot else activity.max_participants,
        taken=held_seats(db, activity.id, slot_id),
        needs_approval=requires_approval(activity.requirements_json),
    )
    registration = existing or Registration(
        registration_id=uuid.uuid7(),
        activity_id=activity.id,
        student_id=user_id,
        slot_id=slot_id,
        # Random rather than UUIDv7: this QR secret must not reveal or follow a clock.
        checkin_token=uuid.uuid4(),
        status=new_status,
    )
    registration.note = note
    registration.registered_at = now
    registration.cancelled_at = None
    registration.review_note = None
    registration.reviewed_by = None
    registration.reviewed_at = None
    if existing is None:
        db.add(registration)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise api_error(status.HTTP_409_CONFLICT, "already_registered") from exc
        db.add(
            RegistrationStatusHistory(
                history_id=uuid.uuid7(),
                registration_id=registration.registration_id,
                from_status=None,
                to_status=new_status,
                changed_by=user_id,
            )
        )
    else:
        record_change(db, registration, new_status, user_id)
    sync_slot_count(db, activity.id, slot_id)
    db.commit()
    return RegistrationResult(
        id=registration.registration_id,
        status=registration.status,
        waitlist_position=waitlist_position(db, registration),
    )


def _load_registration(db: Session, registration_id: uuid.UUID) -> Registration:
    registration = db.get(Registration, registration_id)
    if registration is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "registration_not_found")
    return registration


def activity_id_of(db: Session, registration_id: uuid.UUID) -> uuid.UUID:
    return _load_registration(db, registration_id).activity_id


def cancel_registration(
    db: Session, activity: Activity, registration_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Cancel your own registration. Someone else's looks like it does not exist."""
    registration = _load_registration(db, registration_id)
    if registration.student_id != user_id:
        raise api_error(status.HTTP_404_NOT_FOUND, "registration_not_found")
    if registration.status not in ACTIVE_REGISTRATION:
        raise api_error(status.HTTP_409_CONFLICT, "registration_not_active")
    if not can_cancel_registration(
        status=activity.status, start_at=activity.start_at, now=datetime.now(UTC)
    ):
        raise api_error(status.HTTP_409_CONFLICT, "registration_closed")
    record_change(db, registration, CANCELLED, user_id)
    registration.cancelled_at = datetime.now(UTC)
    promote_waitlist(db, activity, registration.slot_id, user_id)
    sync_slot_count(db, activity.id, registration.slot_id)
    db.commit()


def approve_registration(
    db: Session,
    registration_id: uuid.UUID,
    actor_id: uuid.UUID,
    note: str | None,
) -> None:
    """Approve a pending registration. Its seat is already held."""
    registration = _load_registration(db, registration_id)
    if registration.status != PENDING:
        raise api_error(status.HTTP_409_CONFLICT, "registration_not_pending")
    record_change(db, registration, APPROVED, actor_id, note)
    registration.review_note = note
    registration.reviewed_by = actor_id
    registration.reviewed_at = datetime.now(UTC)
    db.commit()


def reject_registration(
    db: Session,
    activity: Activity,
    registration_id: uuid.UUID,
    actor_id: uuid.UUID,
    note: str | None,
) -> None:
    """Reject any active registration, and give its seat to the next in line."""
    registration = _load_registration(db, registration_id)
    if registration.status not in ACTIVE_REGISTRATION:
        raise api_error(status.HTTP_409_CONFLICT, "registration_not_active")
    record_change(db, registration, REJECTED, actor_id, note)
    registration.review_note = note
    registration.reviewed_by = actor_id
    registration.reviewed_at = datetime.now(UTC)
    promote_waitlist(db, activity, registration.slot_id, actor_id)
    sync_slot_count(db, activity.id, registration.slot_id)
    db.commit()
