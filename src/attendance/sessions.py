"""Check-in sessions. One open at a time for each shift, or for the whole activity."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from src.activities.rules import PUBLISHED
from src.attendance.rules import new_manual_code, new_qr_token, session_is_open
from src.attendance.schemas import SessionCreateRequest, SessionResponse
from src.auth.errors import api_error
from src.models.activities import Activity, ActivitySchedule, ActivitySlot
from src.models.attendance import AttendanceRecord, AttendanceSession, QrCode
from src.validation import validation_failure

CODE_ATTEMPTS = 5


def whole_activity_schedule(db: Session, activity_id: uuid.UUID) -> ActivitySchedule:
    """Sessions need a schedule, so an activity without shifts gets a hidden one.

    It has no slot, so it never shows up as a shift, and no times, so the rule that
    shifts must fit inside the activity skips it.
    """
    schedule = db.scalar(
        select(ActivitySchedule)
        .outerjoin(ActivitySlot, ActivitySlot.schedule_id == ActivitySchedule.id)
        .where(
            ActivitySchedule.activity_id == activity_id,
            ActivitySlot.slot_id.is_(None),
        )
    )
    if schedule is None:
        schedule = ActivitySchedule(id=uuid.uuid7(), activity_id=activity_id)
        db.add(schedule)
        db.flush()
    return schedule


def _resolve_schedule(
    db: Session, activity_id: uuid.UUID, shift_id: uuid.UUID | None
) -> ActivitySchedule:
    if shift_id is not None:
        schedule = db.scalar(
            select(ActivitySchedule)
            .join(ActivitySlot, ActivitySlot.schedule_id == ActivitySchedule.id)
            .where(
                ActivitySlot.slot_id == shift_id,
                ActivitySchedule.activity_id == activity_id,
            )
        )
        if schedule is None:
            raise api_error(status.HTTP_404_NOT_FOUND, "shift_not_found")
        return schedule
    has_shifts = db.scalar(
        select(ActivitySlot.slot_id)
        .join(ActivitySchedule, ActivitySchedule.id == ActivitySlot.schedule_id)
        .where(ActivitySchedule.activity_id == activity_id)
        .limit(1)
    )
    if has_shifts:
        raise validation_failure({"shift_id": "shift_required"})
    return whole_activity_schedule(db, activity_id)


def _unused_manual_code(db: Session, now: datetime) -> str:
    """A typed code must point at one session, so no two open ones may share it."""
    for _ in range(CODE_ATTEMPTS):
        code = new_manual_code()
        taken = db.scalar(
            select(AttendanceSession.session_id).where(
                AttendanceSession.qr_code == code,
                AttendanceSession.status == "open",
                AttendanceSession.closes_at > now,
            )
        )
        if taken is None:
            return code
    raise api_error(status.HTTP_409_CONFLICT, "conflict")


def create_session(
    db: Session,
    activity: Activity,
    actor_id: uuid.UUID,
    payload: SessionCreateRequest,
) -> SessionResponse:
    if activity.status != PUBLISHED:
        raise api_error(status.HTTP_409_CONFLICT, "activity_not_open")
    now = datetime.now(UTC)
    schedule = _resolve_schedule(db, activity.id, payload.shift_id)
    still_open = db.scalar(
        select(AttendanceSession.session_id).where(
            AttendanceSession.schedule_id == schedule.id,
            AttendanceSession.status == "open",
            AttendanceSession.closes_at > now,
        )
    )
    if still_open is not None:
        raise api_error(status.HTTP_409_CONFLICT, "session_already_open")
    closes_at = now + timedelta(minutes=payload.minutes)
    session = AttendanceSession(
        session_id=uuid.uuid7(),
        schedule_id=schedule.id,
        title=payload.title,
        qr_code=_unused_manual_code(db, now),
        opens_at=now,
        closes_at=closes_at,
        status="open",
        created_by=actor_id,
    )
    db.add(session)
    db.flush()
    db.add(
        QrCode(
            code=new_qr_token(),
            session_id=session.session_id,
            schedule_id=schedule.id,
            activity_id=activity.id,
            expires_at=closes_at,
        )
    )
    db.commit()
    return session_response(db, session)


def _count_records(db: Session, session_id: uuid.UUID, *, verified: bool) -> int:
    """A QR scan counts at once, so only typed codes can be waiting for review."""
    condition = (
        (AttendanceRecord.method == "qr") | AttendanceRecord.verified_by.is_not(None)
        if verified
        else (AttendanceRecord.method == "manual")
        & AttendanceRecord.verified_by.is_(None)
    )
    count = db.scalar(
        select(func.count())
        .select_from(AttendanceRecord)
        .where(AttendanceRecord.session_id == session_id, condition)
    )
    return count or 0


def session_response(db: Session, session: AttendanceSession) -> SessionResponse:
    slot = db.scalar(
        select(ActivitySlot).where(ActivitySlot.schedule_id == session.schedule_id)
    )
    is_open = session_is_open(
        status=session.status,
        closes_at=session.closes_at,
        now=datetime.now(UTC),
    )
    token = db.scalar(
        select(QrCode.code).where(QrCode.session_id == session.session_id)
    )
    return SessionResponse(
        id=session.session_id,
        title=session.title,
        shift_id=slot.slot_id if slot else None,
        shift_title=slot.title if slot else None,
        is_open=is_open,
        opens_at=session.opens_at,
        closes_at=session.closes_at,
        manual_code=session.qr_code if is_open else None,
        qr_token=token if is_open else None,
        checked_in_count=_count_records(db, session.session_id, verified=True),
        pending_count=_count_records(db, session.session_id, verified=False),
    )


def list_sessions(db: Session, activity_id: uuid.UUID) -> list[SessionResponse]:
    sessions = db.scalars(
        select(AttendanceSession)
        .join(ActivitySchedule, ActivitySchedule.id == AttendanceSession.schedule_id)
        .where(ActivitySchedule.activity_id == activity_id)
        .order_by(AttendanceSession.session_id.desc())
    ).all()
    return [session_response(db, session) for session in sessions]


def load_session(db: Session, session_id: uuid.UUID) -> AttendanceSession:
    session = db.get(AttendanceSession, session_id)
    if session is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "attendance_session_not_found")
    return session


def activity_id_of_session(db: Session, session: AttendanceSession) -> uuid.UUID:
    schedule = db.get(ActivitySchedule, session.schedule_id)
    if schedule is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "attendance_session_not_found")
    return schedule.activity_id


def close_session(db: Session, session: AttendanceSession) -> None:
    session.status = "closed"
    db.execute(
        update(QrCode)
        .where(QrCode.session_id == session.session_id)
        .values(status="disabled")
    )
    db.commit()


def close_all_sessions(db: Session, activity_id: uuid.UUID) -> None:
    """Close every session when the activity ends. The caller commits."""
    schedule_ids = select(ActivitySchedule.id).where(
        ActivitySchedule.activity_id == activity_id
    )
    db.execute(
        update(AttendanceSession)
        .where(
            AttendanceSession.schedule_id.in_(schedule_ids),
            AttendanceSession.status == "open",
        )
        .values(status="closed")
    )
    db.execute(
        update(QrCode)
        .where(QrCode.activity_id == activity_id)
        .values(status="disabled")
    )
