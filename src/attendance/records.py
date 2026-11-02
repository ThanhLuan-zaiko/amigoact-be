"""What managers do with attendance: the roster, confirming, and correcting."""

import uuid
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.activities.rules import APPROVED, ATTENDED, PUBLISHED
from src.attendance.schemas import RosterEntry
from src.auth.errors import api_error
from src.models.activities import (
    Activity,
    ActivitySchedule,
    ActivitySlot,
    Registration,
)
from src.models.attendance import AttendanceRecord, AttendanceSession
from src.models.auth import User


def _require_open_activity(activity: Activity) -> None:
    """After the activity ends, corrections go through appeals and adjustments."""
    if activity.status != PUBLISHED:
        raise api_error(status.HTTP_409_CONFLICT, "activity_not_editable")


def _session_slot_id(db: Session, session: AttendanceSession) -> uuid.UUID | None:
    return db.scalar(
        select(ActivitySlot.slot_id).where(
            ActivitySlot.schedule_id == session.schedule_id
        )
    )


def session_roster(
    db: Session, activity_id: uuid.UUID, session: AttendanceSession
) -> list[RosterEntry]:
    """Everyone expected at this session. Typed codes that need review come first."""
    slot_id = _session_slot_id(db, session)
    rows = db.execute(
        select(Registration.registration_id, User.full_name, AttendanceRecord)
        .join(User, User.id == Registration.student_id)
        .outerjoin(
            AttendanceRecord,
            (AttendanceRecord.registration_id == Registration.registration_id)
            & (AttendanceRecord.session_id == session.session_id),
        )
        .where(
            Registration.activity_id == activity_id,
            Registration.status.in_((APPROVED, ATTENDED)),
            Registration.slot_id == slot_id
            if slot_id is not None
            else Registration.slot_id.is_(None),
        )
        .order_by(User.full_name, Registration.registration_id)
    ).all()
    entries = [
        RosterEntry(
            registration_id=registration_id,
            full_name=full_name,
            record_id=record.record_id if record else None,
            method=record.method if record else None,
            scanned_at=record.scanned_at if record else None,
            verified=record is not None and is_verified(record),
        )
        for registration_id, full_name, record in rows
    ]
    entries.sort(key=lambda entry: not (entry.record_id and not entry.verified))
    return entries


def is_verified(record: AttendanceRecord) -> bool:
    """A QR scan counts at once. A typed code counts after a manager confirms it."""
    return record.method == "qr" or record.verified_by is not None


def mark_attended(
    db: Session,
    activity: Activity,
    session: AttendanceSession,
    registration_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> None:
    """A manager checks someone in by hand, for example without a phone."""
    _require_open_activity(activity)
    registration = db.get(Registration, registration_id)
    slot_id = _session_slot_id(db, session)
    if (
        registration is None
        or registration.activity_id != activity.id
        or registration.slot_id != slot_id
        or registration.status not in (APPROVED, ATTENDED)
    ):
        raise api_error(status.HTTP_404_NOT_FOUND, "registration_not_found")
    db.add(
        AttendanceRecord(
            record_id=uuid.uuid7(),
            session_id=session.session_id,
            schedule_id=session.schedule_id,
            activity_id=activity.id,
            registration_id=registration_id,
            student_id=registration.student_id,
            method="manual",
            scanned_at=datetime.now(UTC),
            verified_by=actor_id,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise api_error(status.HTTP_409_CONFLICT, "already_checked_in") from exc


def load_record(db: Session, record_id: uuid.UUID) -> AttendanceRecord:
    record = db.get(AttendanceRecord, record_id)
    if record is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "record_not_found")
    return record


def verify_record(
    db: Session, activity: Activity, record: AttendanceRecord, actor_id: uuid.UUID
) -> None:
    _require_open_activity(activity)
    record.verified_by = actor_id
    db.commit()


def delete_record(db: Session, activity: Activity, record: AttendanceRecord) -> None:
    """Refuse a typed code, or undo a check-in made by mistake."""
    _require_open_activity(activity)
    db.delete(record)
    db.commit()


def pending_review_count(db: Session, activity_id: uuid.UUID) -> int:
    rows = db.scalars(
        select(AttendanceRecord.record_id).where(
            AttendanceRecord.activity_id == activity_id,
            AttendanceRecord.method == "manual",
            AttendanceRecord.verified_by.is_(None),
        )
    ).all()
    return len(rows)


def ensure_session_for(db: Session, registration: Registration) -> AttendanceSession:
    """Find a session for an approved appeal, or add a closed one if none ever opened."""
    schedule_id = _schedule_id_for(db, registration)
    session = db.scalar(
        select(AttendanceSession)
        .where(AttendanceSession.schedule_id == schedule_id)
        .order_by(AttendanceSession.session_id.desc())
        .limit(1)
    )
    if session is None:
        session = AttendanceSession(
            session_id=uuid.uuid7(), schedule_id=schedule_id, status="closed"
        )
        db.add(session)
        db.flush()
    return session


def _schedule_id_for(db: Session, registration: Registration) -> uuid.UUID:
    if registration.slot_id is not None:
        slot = db.get(ActivitySlot, registration.slot_id)
        if slot is not None:
            return slot.schedule_id
    schedule = db.scalar(
        select(ActivitySchedule)
        .outerjoin(ActivitySlot, ActivitySlot.schedule_id == ActivitySchedule.id)
        .where(
            ActivitySchedule.activity_id == registration.activity_id,
            ActivitySlot.slot_id.is_(None),
        )
    )
    if schedule is None:
        schedule = ActivitySchedule(
            id=uuid.uuid7(), activity_id=registration.activity_id
        )
        db.add(schedule)
        db.flush()
    return schedule.id
