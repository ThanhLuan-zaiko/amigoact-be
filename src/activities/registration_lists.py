"""Lists of registrations, for an activity's managers and for a volunteer."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.activities.queries import waitlist_position
from src.activities.rules import (
    ACTIVE_REGISTRATION,
    can_appeal,
    can_cancel_registration,
)
from src.activities.schemas import (
    ActivityRegistration,
    MyRegistration,
    RegistrationPage,
)
from src.models.activities import Activity, ActivitySlot, Registration
from src.models.attendance import AttendanceAppeal, AttendanceRecord
from src.models.auth import User
from src.models.organizations import Organization
from src.pagination import count_rows


def list_activity_registrations(
    db: Session,
    activity_id: uuid.UUID,
    wanted_status: str | None,
    limit: int,
    offset: int,
) -> RegistrationPage:
    query = (
        select(Registration, User.full_name, ActivitySlot.title)
        .join(User, User.id == Registration.student_id)
        .outerjoin(ActivitySlot, ActivitySlot.slot_id == Registration.slot_id)
        .where(Registration.activity_id == activity_id)
    )
    if wanted_status:
        query = query.where(Registration.status == wanted_status)
    rows = db.execute(
        query.order_by(Registration.registered_at, Registration.registration_id)
        .limit(limit + 1)
        .offset(offset)
    ).all()
    return RegistrationPage(
        items=[
            ActivityRegistration(
                id=registration.registration_id,
                user_id=registration.student_id,
                full_name=full_name,
                status=registration.status,
                note=registration.note,
                review_note=registration.review_note,
                shift_id=registration.slot_id,
                shift_title=shift_title,
                registered_at=registration.registered_at,
            )
            for registration, full_name, shift_title in rows[:limit]
        ],
        next_offset=offset + limit if len(rows) > limit else None,
        total=count_rows(db, query),
    )


def _attendance_state(db: Session, registration_id: uuid.UUID) -> str | None:
    rows = db.execute(
        select(AttendanceRecord.method, AttendanceRecord.verified_by).where(
            AttendanceRecord.registration_id == registration_id
        )
    ).all()
    if any(method == "qr" or verifier is not None for method, verifier in rows):
        return "verified"
    return "pending" if rows else None


def _latest_appeal_status(
    db: Session, activity_id: uuid.UUID, user_id: uuid.UUID
) -> str | None:
    return db.scalar(
        select(AttendanceAppeal.status)
        .where(
            AttendanceAppeal.activity_id == activity_id,
            AttendanceAppeal.student_id == user_id,
        )
        .order_by(AttendanceAppeal.appeal_id.desc())
        .limit(1)
    )


def list_my_registrations(db: Session, user_id: uuid.UUID) -> list[MyRegistration]:
    """Newest activity first. Deleted activities and organizations drop out."""
    now = datetime.now(UTC)
    rows = db.execute(
        select(Registration, Activity, Organization.name, ActivitySlot.title)
        .join(Activity, Activity.id == Registration.activity_id)
        .join(Organization, Organization.id == Activity.org_id)
        .outerjoin(ActivitySlot, ActivitySlot.slot_id == Registration.slot_id)
        .where(
            Registration.student_id == user_id,
            Activity.deleted_at.is_(None),
            Organization.deleted_at.is_(None),
            Organization.status == "active",
        )
        .order_by(Activity.start_at.desc(), Registration.registration_id)
    ).all()
    items = []
    for registration, activity, org_name, shift_title in rows:
        attendance = _attendance_state(db, registration.registration_id)
        appeal_status = _latest_appeal_status(db, activity.id, user_id)
        items.append(
            MyRegistration(
                id=registration.registration_id,
                status=registration.status,
                note=registration.note,
                review_note=registration.review_note,
                registered_at=registration.registered_at,
                waitlist_position=waitlist_position(db, registration),
                shift_title=shift_title,
                can_cancel=registration.status in ACTIVE_REGISTRATION
                and can_cancel_registration(
                    status=activity.status, start_at=activity.start_at, now=now
                ),
                attendance=attendance,
                can_appeal=attendance != "verified"
                and appeal_status != "pending"
                and can_appeal(
                    activity_status=activity.status,
                    start_at=activity.start_at,
                    registration_status=registration.status,
                    now=now,
                ),
                appeal_status=appeal_status,
                activity_id=activity.id,
                activity_title=activity.title,
                activity_status=activity.status,
                start_at=activity.start_at,
                location=activity.location,
                organization_name=org_name,
            )
        )
    return items
