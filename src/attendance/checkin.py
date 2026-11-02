"""Volunteers checking themselves in, by QR or by typing the session code.

A scanned QR counts at once, because it proves the person can see the screen. A typed
code can be passed around, so it waits for a manager to confirm it.
"""

import uuid
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.activities.rules import APPROVED, ATTENDED, PUBLISHED
from src.attendance.rules import session_is_open
from src.attendance.schemas import CheckInRequest, CheckInResult
from src.auth.deps import ClientInfo
from src.auth.errors import api_error
from src.auth.rate_limit import enforce_rate_limit
from src.models.activities import (
    Activity,
    ActivitySchedule,
    ActivitySlot,
    Registration,
)
from src.models.attendance import (
    AttendanceRecord,
    AttendanceSession,
    QrCode,
    QrScanLog,
)

CHECKIN_LIMIT = 30
CHECKIN_WINDOW = 15 * 60


def registration_for_session(
    db: Session, session: AttendanceSession, user_id: uuid.UUID
) -> Registration | None:
    """Find the registration this session is for: its shift, or the whole activity."""
    schedule = db.get(ActivitySchedule, session.schedule_id)
    if schedule is None:
        return None
    slot_id = db.scalar(
        select(ActivitySlot.slot_id).where(ActivitySlot.schedule_id == schedule.id)
    )
    return db.scalar(
        select(Registration).where(
            Registration.activity_id == schedule.activity_id,
            Registration.student_id == user_id,
            Registration.slot_id == slot_id
            if slot_id is not None
            else Registration.slot_id.is_(None),
        )
    )


def _log_scan(
    db: Session,
    code: str,
    user_id: uuid.UUID,
    result: str,
    client: ClientInfo,
) -> None:
    db.add(
        QrScanLog(
            log_id=uuid.uuid7(),
            qr_code=code,
            student_id=user_id,
            result=result,
            device_info=client.user_agent,
        )
    )
    db.commit()


def _find_session(
    db: Session, payload: CheckInRequest, now: datetime
) -> AttendanceSession | None:
    if payload.token is not None:
        session_id = db.scalar(
            select(QrCode.session_id).where(QrCode.code == payload.token)
        )
        return db.get(AttendanceSession, session_id) if session_id else None
    return db.scalar(
        select(AttendanceSession)
        .where(AttendanceSession.qr_code == payload.code)
        .order_by(
            (AttendanceSession.closes_at > now).desc(),
            AttendanceSession.session_id.desc(),
        )
        .limit(1)
    )


def check_in(
    db: Session,
    user_id: uuid.UUID,
    payload: CheckInRequest,
    client: ClientInfo,
) -> CheckInResult:
    enforce_rate_limit(db, f"checkin:{user_id}", CHECKIN_LIMIT, CHECKIN_WINDOW)
    now = datetime.now(UTC)
    code = payload.token or payload.code or ""
    uses_qr = payload.token is not None

    session = _find_session(db, payload, now)
    if session is None:
        _log_scan(db, code, user_id, "invalid", client)
        raise api_error(status.HTTP_404_NOT_FOUND, "checkin_code_invalid")
    schedule = db.get(ActivitySchedule, session.schedule_id)
    activity = db.get(Activity, schedule.activity_id) if schedule else None
    if (
        schedule is None
        or activity is None
        or activity.status != PUBLISHED
        or not session_is_open(
            status=session.status, closes_at=session.closes_at, now=now
        )
    ):
        _log_scan(db, code, user_id, "expired", client)
        raise api_error(status.HTTP_409_CONFLICT, "checkin_session_closed")

    registration = registration_for_session(db, session, user_id)
    if registration is None or registration.status not in (APPROVED, ATTENDED):
        _log_scan(db, code, user_id, "invalid", client)
        raise api_error(status.HTTP_403_FORBIDDEN, "not_registered_for_session")

    record = AttendanceRecord(
        record_id=uuid.uuid7(),
        session_id=session.session_id,
        schedule_id=schedule.id,
        activity_id=activity.id,
        registration_id=registration.registration_id,
        student_id=user_id,
        method="qr" if uses_qr else "manual",
        scanned_at=now,
    )
    activity_id = activity.id
    activity_title = activity.title
    session_title = session.title
    db.add(record)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        _log_scan(db, code, user_id, "duplicate", client)
        raise api_error(status.HTTP_409_CONFLICT, "already_checked_in") from exc
    if uses_qr:
        db.execute(
            update(QrCode)
            .where(QrCode.code == code)
            .values(used_count=QrCode.used_count + 1)
        )
    _log_scan(db, code, user_id, "accepted", client)
    return CheckInResult(
        status="accepted" if uses_qr else "pending_review",
        activity_id=activity_id,
        activity_title=activity_title,
        session_title=session_title,
    )
