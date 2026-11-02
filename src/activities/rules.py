"""Business rules for activities. Pure functions, so they need no database."""

from datetime import datetime
from typing import Any

DRAFT = "draft"
PUBLISHED = "published"
COMPLETED = "completed"
CANCELLED = "cancelled"

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
WAITLISTED = "waitlisted"
ATTENDED = "attended"

# A pending registration holds its seat, so approvals can never overfill an activity.
HOLDS_SEAT = (PENDING, APPROVED, ATTENDED)
ACTIVE_REGISTRATION = (PENDING, APPROVED, WAITLISTED)
EDITABLE_STATUSES = (DRAFT, PUBLISHED)


def requires_approval(requirements: dict[str, Any] | None) -> bool:
    return bool((requirements or {}).get("requires_approval", False))


def initial_status(*, capacity: int | None, taken: int, needs_approval: bool) -> str:
    """A full activity puts the volunteer on the waitlist. No capacity means no limit."""
    if capacity is not None and taken >= capacity:
        return WAITLISTED
    return admitted_status(needs_approval)


def admitted_status(needs_approval: bool) -> str:
    return PENDING if needs_approval else APPROVED


def registration_is_open(
    *,
    status: str,
    start_at: datetime | None,
    deadline: datetime | None,
    now: datetime,
) -> bool:
    """Registration closes at the deadline, or at the start without a deadline."""
    closes_at = deadline or start_at
    return status == PUBLISHED and closes_at is not None and now < closes_at


def can_cancel_registration(
    *, status: str, start_at: datetime | None, now: datetime
) -> bool:
    return status == PUBLISHED and start_at is not None and now < start_at


def can_appeal(
    *,
    activity_status: str,
    start_at: datetime | None,
    registration_status: str,
    now: datetime,
) -> bool:
    """An appeal makes sense once the activity has started, for someone expected there."""
    return (
        activity_status in (PUBLISHED, COMPLETED)
        and start_at is not None
        and start_at <= now
        and registration_status in (APPROVED, ATTENDED)
    )


def schedule_errors(
    start_at: datetime | None,
    end_at: datetime | None,
    deadline: datetime | None,
) -> dict[str, str]:
    """Check that the times of an activity make sense together."""
    errors: dict[str, str] = {}
    if start_at and end_at and end_at <= start_at:
        errors["end_at"] = "end_before_start"
    if start_at and deadline and deadline > start_at:
        errors["registration_deadline"] = "deadline_after_start"
    return errors


def publish_errors(
    *,
    start_at: datetime | None,
    end_at: datetime | None,
    deadline: datetime | None,
    location: str | None,
    is_remote: bool,
    now: datetime,
) -> dict[str, str]:
    """An activity must be complete and still ahead before volunteers can see it."""
    errors = schedule_errors(start_at, end_at, deadline)
    if start_at is None:
        errors["start_at"] = "required"
    elif start_at <= now:
        errors["start_at"] = "start_in_past"
    if end_at is None:
        errors["end_at"] = "required"
    if deadline is not None and deadline <= now:
        errors.setdefault("registration_deadline", "deadline_in_past")
    if not is_remote and not location:
        errors["location"] = "required"
    return errors


def shift_errors(
    *,
    start_at: datetime,
    end_at: datetime,
    activity_start: datetime | None,
    activity_end: datetime | None,
) -> dict[str, str]:
    """A shift must have a real duration and stay inside the activity."""
    errors: dict[str, str] = {}
    if end_at <= start_at:
        errors["end_at"] = "end_before_start"
    if activity_start and start_at < activity_start:
        errors["start_at"] = "shift_outside_activity"
    if activity_end and end_at > activity_end:
        errors["end_at"] = "shift_outside_activity"
    return errors


def times_overlap(
    first_start: datetime | None,
    first_end: datetime | None,
    second_start: datetime | None,
    second_end: datetime | None,
) -> bool:
    """Touching end to end is not an overlap, so back-to-back shifts are allowed."""
    if not (first_start and first_end and second_start and second_end):
        return False
    return first_start < second_end and second_start < first_end
