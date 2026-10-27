"""Phase and registration-window rules shared by the browse feed and registrations.

Pure functions over naive UTC datetimes. They live in core so that
registrations can enforce the same window without importing the activities
feature.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

# A published activity without end_at is treated as lasting this long.
DEFAULT_DURATION: Final = timedelta(hours=3)
_OPEN_STATUSES: Final = frozenset({"published", "ongoing"})


def utc_naive(moment: datetime | None) -> datetime | None:
    """Store-shaped datetime: naive UTC, or None passed through."""
    if moment is None or moment.tzinfo is None:
        return moment
    return moment.astimezone(UTC).replace(tzinfo=None)


def classify_phase(
    status: str,
    start_at: datetime | None,
    end_at: datetime | None,
    now: datetime,
) -> str | None:
    """Map lifecycle state plus times onto upcoming, ongoing or past.

    Organizers often never flip published to completed, so a published
    activity whose window has closed counts as past. Returns None for
    states the public feed never serves.
    """
    if status == "completed":
        return "past"
    if status == "ongoing":
        return "ongoing"
    if status != "published" or start_at is None:
        return None
    if start_at > now:
        return "upcoming"
    closes_at = end_at or start_at + DEFAULT_DURATION
    return "ongoing" if closes_at >= now else "past"


def is_registration_open(
    status: str,
    deadline: datetime | None,
    phase: str | None,
    now: datetime,
) -> bool:
    """Seats never close sign-ups: a full activity takes the waitlist."""
    if status not in _OPEN_STATUSES or phase in (None, "past"):
        return False
    return deadline is None or deadline > now
