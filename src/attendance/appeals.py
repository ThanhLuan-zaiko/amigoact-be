"""Appeals: a volunteer who was there but has no attendance can ask for a review."""

import uuid
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.activities.rules import APPROVED, ATTENDED, COMPLETED, can_appeal
from src.attendance.hours import award_registration
from src.attendance.records import ensure_session_for, is_verified
from src.attendance.schemas import AppealRegistration, AppealResponse
from src.auth.errors import api_error
from src.models.activities import Activity, ActivitySlot, Registration
from src.models.attendance import AttendanceAppeal, AttendanceRecord
from src.models.auth import User
from src.notifications.events import activity_data, notify
from src.validation import validation_failure

PENDING = "pending"


def _has_verified_record(db: Session, registration_id: uuid.UUID) -> bool:
    records = db.scalars(
        select(AttendanceRecord).where(
            AttendanceRecord.registration_id == registration_id
        )
    ).all()
    return any(is_verified(record) for record in records)


def create_appeal(
    db: Session,
    activity: Activity,
    registration: Registration,
    user_id: uuid.UUID,
    reason: str,
) -> None:
    if registration.student_id != user_id:
        raise api_error(status.HTTP_404_NOT_FOUND, "registration_not_found")
    if not can_appeal(
        activity_status=activity.status,
        start_at=activity.start_at,
        registration_status=registration.status,
        now=datetime.now(UTC),
    ):
        raise api_error(status.HTTP_409_CONFLICT, "appeal_not_allowed")
    if _has_verified_record(db, registration.registration_id):
        raise api_error(status.HTTP_409_CONFLICT, "already_checked_in")
    pending = db.scalar(
        select(AttendanceAppeal.appeal_id).where(
            AttendanceAppeal.activity_id == activity.id,
            AttendanceAppeal.student_id == user_id,
            AttendanceAppeal.status == PENDING,
        )
    )
    if pending is not None:
        raise api_error(status.HTTP_409_CONFLICT, "appeal_already_pending")
    db.add(
        AttendanceAppeal(
            appeal_id=uuid.uuid7(),
            activity_id=activity.id,
            student_id=user_id,
            reason=reason,
        )
    )
    db.commit()


def _open_registrations(
    db: Session, activity_id: uuid.UUID, student_id: uuid.UUID
) -> list[tuple[Registration, str | None]]:
    """What the appeal could cover: registrations still without attendance."""
    rows = db.execute(
        select(Registration, ActivitySlot.title)
        .outerjoin(ActivitySlot, ActivitySlot.slot_id == Registration.slot_id)
        .where(
            Registration.activity_id == activity_id,
            Registration.student_id == student_id,
            Registration.status.in_((APPROVED, ATTENDED)),
        )
        .order_by(Registration.registration_id)
    ).all()
    return [
        (registration, title)
        for registration, title in rows
        if not _has_verified_record(db, registration.registration_id)
    ]


def list_appeals(
    db: Session, activity_id: uuid.UUID, wanted_status: str | None
) -> list[AppealResponse]:
    query = (
        select(AttendanceAppeal, User.full_name)
        .join(User, User.id == AttendanceAppeal.student_id)
        .where(AttendanceAppeal.activity_id == activity_id)
    )
    if wanted_status:
        query = query.where(AttendanceAppeal.status == wanted_status)
    rows = db.execute(query.order_by(AttendanceAppeal.appeal_id)).all()
    return [
        AppealResponse(
            id=appeal.appeal_id,
            user_id=appeal.student_id,
            full_name=full_name,
            reason=appeal.reason,
            status=appeal.status,
            created_at=appeal.created_at,
            resolved_at=appeal.resolved_at,
            registrations=[
                AppealRegistration(
                    registration_id=registration.registration_id,
                    shift_title=title,
                )
                for registration, title in _open_registrations(
                    db, activity_id, appeal.student_id
                )
            ]
            if appeal.status == PENDING
            else [],
        )
        for appeal, full_name in rows
    ]


def load_appeal(db: Session, appeal_id: uuid.UUID) -> AttendanceAppeal:
    appeal = db.get(AttendanceAppeal, appeal_id)
    if appeal is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "appeal_not_found")
    return appeal


def _pick_registration(
    db: Session,
    appeal: AttendanceAppeal,
    registration_id: uuid.UUID | None,
) -> Registration:
    candidates = [
        registration
        for registration, _ in _open_registrations(
            db, appeal.activity_id, appeal.student_id
        )
    ]
    if registration_id is not None:
        for registration in candidates:
            if registration.registration_id == registration_id:
                return registration
        raise api_error(status.HTTP_404_NOT_FOUND, "registration_not_found")
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise api_error(status.HTTP_409_CONFLICT, "already_checked_in")
    raise validation_failure({"registration_id": "registration_required"})


def approve_appeal(
    db: Session,
    activity: Activity,
    appeal: AttendanceAppeal,
    actor_id: uuid.UUID,
    registration_id: uuid.UUID | None,
) -> None:
    """Confirm attendance. After the activity has ended, this awards the hours too."""
    if appeal.status != PENDING:
        raise api_error(status.HTTP_409_CONFLICT, "appeal_not_pending")
    registration = _pick_registration(db, appeal, registration_id)
    session = ensure_session_for(db, registration)
    record = db.scalar(
        select(AttendanceRecord).where(
            AttendanceRecord.registration_id == registration.registration_id,
            AttendanceRecord.session_id == session.session_id,
        )
    )
    if record is None:
        db.add(
            AttendanceRecord(
                record_id=uuid.uuid7(),
                session_id=session.session_id,
                schedule_id=session.schedule_id,
                activity_id=activity.id,
                registration_id=registration.registration_id,
                student_id=registration.student_id,
                method="manual",
                scanned_at=datetime.now(UTC),
                verified_by=actor_id,
            )
        )
    else:
        record.verified_by = actor_id
    if activity.status == COMPLETED:
        award_registration(db, activity, registration, actor_id)
    appeal.status = "approved"
    appeal.resolved_by = actor_id
    appeal.resolved_at = datetime.now(UTC)
    notify(db, appeal.student_id, "appeal_approved", activity_data(db, activity.id))
    db.commit()


def reject_appeal(db: Session, appeal: AttendanceAppeal, actor_id: uuid.UUID) -> None:
    if appeal.status != PENDING:
        raise api_error(status.HTTP_409_CONFLICT, "appeal_not_pending")
    appeal.status = "rejected"
    appeal.resolved_by = actor_id
    appeal.resolved_at = datetime.now(UTC)
    notify(
        db,
        appeal.student_id,
        "appeal_rejected",
        activity_data(db, appeal.activity_id),
    )
    db.commit()
