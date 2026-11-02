"""The volunteer hour ledger. It only grows: corrections are new rows."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.activities.registrations import record_change
from src.activities.rules import APPROVED, ATTENDED
from src.attendance.records import is_verified, pending_review_count
from src.attendance.rules import apply_rule, duration_hours, term_of
from src.attendance.schemas import (
    ActivityHoursEntry,
    AdjustmentRequest,
    HourEntry,
    HourRuleRequest,
    HourRuleResponse,
    MyHours,
    TermHours,
)
from src.attendance.sessions import close_all_sessions
from src.auth.errors import api_error
from src.models.activities import Activity, ActivitySlot, Registration
from src.models.attendance import (
    AttendanceRecord,
    HourAdjustment,
    HourRule,
    VolunteerHourLedger,
)
from src.models.auth import User
from src.models.organizations import Organization

ENTRY_LIMIT = 100
ATTENDANCE_SOURCE = "attendance"
ADJUSTMENT_SOURCE = "adjustment"


def _org_rule(db: Session, org_id: uuid.UUID) -> HourRule | None:
    return db.scalar(
        select(HourRule).where(
            HourRule.org_id == org_id,
            HourRule.category_id.is_(None),
            HourRule.term.is_(None),
            HourRule.is_active.is_(True),
        )
    )


def _hours_in_term(
    db: Session, org_id: uuid.UUID, student_id: uuid.UUID, term: str
) -> Decimal:
    total = db.scalar(
        select(func.sum(VolunteerHourLedger.hours)).where(
            VolunteerHourLedger.org_id == org_id,
            VolunteerHourLedger.student_id == student_id,
            VolunteerHourLedger.term == term,
            VolunteerHourLedger.status == "approved",
        )
    )
    return total or Decimal("0.00")


def _base_hours(db: Session, activity: Activity, registration: Registration) -> Decimal:
    """A shift earns its own length. An activity without shifts earns its set hours."""
    if registration.slot_id is not None:
        slot = db.get(ActivitySlot, registration.slot_id)
        return duration_hours(slot.start_at, slot.end_at) if slot else Decimal("0.00")
    if activity.hours_awarded is None:
        raise api_error(status.HTTP_409_CONFLICT, "hours_required")
    return activity.hours_awarded


def award_registration(
    db: Session,
    activity: Activity,
    registration: Registration,
    actor_id: uuid.UUID,
) -> None:
    """Add the attendance entry once, and mark the registration as attended."""
    already = db.scalar(
        select(VolunteerHourLedger.entry_id).where(
            VolunteerHourLedger.registration_id == registration.registration_id,
            VolunteerHourLedger.source == ATTENDANCE_SOURCE,
        )
    )
    if already is not None:
        return
    term = term_of(activity.start_at)
    rule = _org_rule(db, activity.org_id)
    hours = apply_rule(
        _base_hours(db, activity, registration),
        multiplier=rule.multiplier if rule else Decimal(1),
        cap=rule.cap_hours if rule else None,
        already_in_term=_hours_in_term(
            db, activity.org_id, registration.student_id, term
        ),
    )
    db.add(
        VolunteerHourLedger(
            entry_id=uuid.uuid7(),
            student_id=registration.student_id,
            activity_id=activity.id,
            org_id=activity.org_id,
            source=ATTENDANCE_SOURCE,
            hours=hours,
            term=term,
            registration_id=registration.registration_id,
            status="approved",
            approved_by=actor_id,
            approved_at=datetime.now(UTC),
            recorded_by=actor_id,
        )
    )
    record_change(db, registration, ATTENDED, actor_id, "attendance_confirmed")
    db.flush()


def award_for_completion(db: Session, activity: Activity, actor_id: uuid.UUID) -> None:
    """Close the sessions and award everyone with confirmed attendance.

    The caller commits, together with the activity's status change.
    """
    if pending_review_count(db, activity.id) > 0:
        raise api_error(status.HTTP_409_CONFLICT, "attendance_pending_review")
    close_all_sessions(db, activity.id)
    records = db.scalars(
        select(AttendanceRecord).where(AttendanceRecord.activity_id == activity.id)
    ).all()
    registration_ids = {
        record.registration_id for record in records if is_verified(record)
    }
    registrations = db.scalars(
        select(Registration)
        .where(
            Registration.registration_id.in_(registration_ids),
            Registration.status.in_((APPROVED, ATTENDED)),
        )
        .order_by(Registration.registration_id)
    ).all()
    for registration in registrations:
        award_registration(db, activity, registration, actor_id)


def adjust_hours(
    db: Session,
    activity: Activity,
    actor_id: uuid.UUID,
    payload: AdjustmentRequest,
) -> None:
    """Correct a volunteer's hours for one activity, with the reason on record."""
    current = db.scalar(
        select(func.sum(VolunteerHourLedger.hours)).where(
            VolunteerHourLedger.activity_id == activity.id,
            VolunteerHourLedger.student_id == payload.user_id,
            VolunteerHourLedger.status == "approved",
        )
    )
    if current is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "hours_not_found")
    if current + payload.delta_hours < 0:
        raise api_error(status.HTTP_409_CONFLICT, "hours_would_go_negative")
    now = datetime.now(UTC)
    db.add(
        HourAdjustment(
            adjustment_id=uuid.uuid7(),
            student_id=payload.user_id,
            activity_id=activity.id,
            delta_hours=payload.delta_hours,
            reason=payload.reason,
            created_by=actor_id,
        )
    )
    db.add(
        VolunteerHourLedger(
            entry_id=uuid.uuid7(),
            student_id=payload.user_id,
            activity_id=activity.id,
            org_id=activity.org_id,
            source=ADJUSTMENT_SOURCE,
            hours=payload.delta_hours,
            term=term_of(activity.start_at),
            status="approved",
            approved_by=actor_id,
            approved_at=now,
            recorded_by=actor_id,
            note=payload.reason,
        )
    )
    db.commit()


def activity_hours(db: Session, activity_id: uuid.UUID) -> list[ActivityHoursEntry]:
    rows = db.execute(
        select(User.id, User.full_name, func.sum(VolunteerHourLedger.hours))
        .join(VolunteerHourLedger, VolunteerHourLedger.student_id == User.id)
        .where(
            VolunteerHourLedger.activity_id == activity_id,
            VolunteerHourLedger.status == "approved",
        )
        .group_by(User.id, User.full_name)
        .order_by(User.full_name)
    ).all()
    return [
        ActivityHoursEntry(user_id=user_id, full_name=name, hours=float(hours))
        for user_id, name, hours in rows
    ]


def my_hours(db: Session, user_id: uuid.UUID) -> MyHours:
    approved = (
        VolunteerHourLedger.student_id == user_id,
        VolunteerHourLedger.status == "approved",
    )
    terms = db.execute(
        select(VolunteerHourLedger.term, func.sum(VolunteerHourLedger.hours))
        .where(*approved)
        .group_by(VolunteerHourLedger.term)
        .order_by(VolunteerHourLedger.term.desc())
    ).all()
    rows = db.execute(
        select(VolunteerHourLedger, Activity.title, Organization.name)
        .outerjoin(Activity, Activity.id == VolunteerHourLedger.activity_id)
        .outerjoin(Organization, Organization.id == VolunteerHourLedger.org_id)
        .where(*approved)
        .order_by(VolunteerHourLedger.entry_id.desc())
        .limit(ENTRY_LIMIT)
    ).all()
    return MyHours(
        total=float(sum((hours for _, hours in terms), Decimal(0))),
        by_term=[
            TermHours(term=term or "", hours=float(hours)) for term, hours in terms
        ],
        entries=[
            HourEntry(
                id=entry.entry_id,
                hours=float(entry.hours),
                source=entry.source,
                term=entry.term,
                note=entry.note,
                recorded_at=entry.recorded_at,
                activity_id=entry.activity_id,
                activity_title=title,
                organization_name=org_name,
            )
            for entry, title, org_name in rows
        ],
    )


def get_hour_rule(db: Session, org_id: uuid.UUID) -> HourRuleResponse:
    rule = _org_rule(db, org_id)
    if rule is None:
        return HourRuleResponse(multiplier=1.0, cap_hours=None)
    cap = rule.cap_hours
    return HourRuleResponse(
        multiplier=float(rule.multiplier),
        cap_hours=float(cap) if cap is not None else None,
    )


def set_hour_rule(
    db: Session, org_id: uuid.UUID, payload: HourRuleRequest
) -> HourRuleResponse:
    """Applies to hours awarded from now on. Past entries in the ledger stay as they are."""
    rule = _org_rule(db, org_id)
    if rule is None:
        rule = HourRule(rule_id=uuid.uuid7(), org_id=org_id)
        db.add(rule)
    rule.multiplier = payload.multiplier
    rule.cap_hours = payload.cap_hours
    db.commit()
    return get_hour_rule(db, org_id)
