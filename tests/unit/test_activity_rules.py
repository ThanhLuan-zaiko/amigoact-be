from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.activities.rules import (
    can_cancel_registration,
    initial_status,
    publish_errors,
    registration_is_open,
    requires_approval,
    schedule_errors,
    shift_errors,
    times_overlap,
)
from src.activities.schemas import (
    ActivityCreateRequest,
    ActivityUpdateRequest,
    RegisterRequest,
    ShiftRequest,
)
from src.models import activities  # noqa: F401  registers the tables
from src.models.base import Base

NOW = datetime(2026, 6, 1, 12, tzinfo=UTC)


def after(hours: float) -> datetime:
    return NOW + timedelta(hours=hours)


def test_activity_models_register_their_tables() -> None:
    assert {
        "activities",
        "activity_schedules",
        "activity_slots",
        "registrations",
        "registration_status_history",
    } <= set(Base.metadata.tables)


@pytest.mark.parametrize(
    ("capacity", "taken", "needs_approval", "expected"),
    [
        (None, 1000, False, "approved"),
        (None, 1000, True, "pending"),
        (2, 1, False, "approved"),
        (2, 1, True, "pending"),
        (2, 2, False, "waitlisted"),
        (2, 3, True, "waitlisted"),
    ],
)
def test_initial_status(
    capacity: int | None, taken: int, needs_approval: bool, expected: str
) -> None:
    status = initial_status(
        capacity=capacity, taken=taken, needs_approval=needs_approval
    )
    assert status == expected


def test_requires_approval_defaults_to_false() -> None:
    assert requires_approval(None) is False
    assert requires_approval({}) is False
    assert requires_approval({"requires_approval": True}) is True


def test_registration_closes_at_the_deadline_or_else_the_start() -> None:
    def is_open(start: datetime | None, deadline: datetime | None) -> bool:
        return registration_is_open(
            status="published", start_at=start, deadline=deadline, now=NOW
        )

    assert is_open(after(5), None)
    assert not is_open(after(-1), None)
    assert is_open(after(5), after(1))
    assert not is_open(after(5), after(-1))
    assert not is_open(None, None)


@pytest.mark.parametrize("status", ["draft", "completed", "cancelled"])
def test_registration_needs_a_published_activity(status: str) -> None:
    assert not registration_is_open(
        status=status, start_at=after(5), deadline=None, now=NOW
    )


def test_cancelling_stops_when_the_activity_starts() -> None:
    assert can_cancel_registration(status="published", start_at=after(1), now=NOW)
    assert not can_cancel_registration(status="published", start_at=after(-1), now=NOW)
    assert not can_cancel_registration(status="cancelled", start_at=after(1), now=NOW)


def test_schedule_errors_compare_the_times() -> None:
    assert schedule_errors(after(1), after(2), after(0)) == {}
    assert schedule_errors(after(2), after(1), None) == {"end_at": "end_before_start"}
    assert schedule_errors(after(2), after(2), None) == {"end_at": "end_before_start"}
    assert schedule_errors(after(1), after(2), after(3)) == {
        "registration_deadline": "deadline_after_start"
    }


def test_publish_needs_times_and_a_place() -> None:
    errors = publish_errors(
        start_at=None,
        end_at=None,
        deadline=None,
        location=None,
        is_remote=False,
        now=NOW,
    )
    assert errors == {
        "start_at": "required",
        "end_at": "required",
        "location": "required",
    }


def test_publish_skips_the_place_for_remote_activities() -> None:
    errors = publish_errors(
        start_at=after(1),
        end_at=after(2),
        deadline=None,
        location=None,
        is_remote=True,
        now=NOW,
    )
    assert errors == {}


def test_publish_rejects_times_already_gone() -> None:
    errors = publish_errors(
        start_at=after(-2),
        end_at=after(-1),
        deadline=after(-3),
        location="San",
        is_remote=False,
        now=NOW,
    )
    assert errors == {
        "start_at": "start_in_past",
        "registration_deadline": "deadline_in_past",
    }


def test_shift_must_stay_inside_the_activity() -> None:
    def check(start: float, end: float) -> dict[str, str]:
        return shift_errors(
            start_at=after(start),
            end_at=after(end),
            activity_start=after(0),
            activity_end=after(10),
        )

    assert check(1, 2) == {}
    assert check(0, 10) == {}
    assert check(2, 1) == {"end_at": "end_before_start"}
    assert check(-1, 2) == {"start_at": "shift_outside_activity"}
    assert check(1, 11) == {"end_at": "shift_outside_activity"}


def test_back_to_back_shifts_do_not_overlap() -> None:
    assert not times_overlap(after(1), after(2), after(2), after(3))
    assert times_overlap(after(1), after(3), after(2), after(4))
    assert times_overlap(after(1), after(4), after(2), after(3))
    assert not times_overlap(None, after(2), after(1), after(3))


def test_create_request_rejects_a_time_without_a_zone() -> None:
    with pytest.raises(ValidationError) as caught:
        ActivityCreateRequest.model_validate(
            {"title": "Mua he xanh", "start_at": "2026-06-01T08:00:00"}
        )
    assert caught.value.errors()[0]["type"] == "timezone_aware"


def test_hours_allow_two_decimal_places() -> None:
    payload = ActivityCreateRequest(title="Mua he", hours_awarded=Decimal("2.50"))
    assert payload.hours_awarded == Decimal("2.50")
    with pytest.raises(ValidationError):
        ActivityCreateRequest(title="Mua he", hours_awarded=Decimal("2.555"))


@pytest.mark.parametrize("title", ["ab", "...", "a\x00bc", "x" * 201])
def test_title_rules(title: str) -> None:
    with pytest.raises(ValidationError):
        ActivityCreateRequest(title=title)


@pytest.mark.parametrize("field", ["title", "is_remote", "requires_approval"])
def test_update_rejects_null_for_required_fields(field: str) -> None:
    with pytest.raises(ValidationError) as caught:
        ActivityUpdateRequest.model_validate({field: None})
    assert caught.value.errors()[0]["loc"] == (field,)


def test_shift_request_needs_a_positive_capacity() -> None:
    with pytest.raises(ValidationError):
        ShiftRequest.model_validate(
            {
                "title": "Ca",
                "start_at": NOW.isoformat(),
                "end_at": after(1).isoformat(),
                "capacity": 0,
            }
        )


def test_register_request_accepts_only_uuid7_shifts() -> None:
    with pytest.raises(ValidationError) as caught:
        RegisterRequest.model_validate(
            {"shift_id": "9f1f1c2e-3b4a-4c5d-8e6f-7a8b9c0d1e2f"}
        )
    assert caught.value.errors()[0]["type"] == "uuid_invalid"
