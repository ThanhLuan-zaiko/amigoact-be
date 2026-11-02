from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.attendance.rules import (
    CODE_ALPHABET,
    CODE_LENGTH,
    apply_rule,
    duration_hours,
    new_manual_code,
    new_qr_token,
    session_is_open,
    term_of,
)
from src.attendance.schemas import (
    AdjustmentRequest,
    AppealRequest,
    CheckInRequest,
    HourRuleRequest,
    SessionCreateRequest,
)
from src.models import attendance  # noqa: F401  registers the tables
from src.models.base import Base

NOW = datetime(2026, 6, 1, 12, tzinfo=UTC)
USER_V7 = "01980000-0000-7000-8000-000000000000"


def test_attendance_models_register_their_tables() -> None:
    assert {
        "attendance_sessions",
        "qr_codes",
        "qr_scan_logs",
        "attendance_records",
        "attendance_appeals",
        "volunteer_hour_ledger",
        "hour_adjustments",
        "hour_rules",
    } <= set(Base.metadata.tables)


def test_manual_code_avoids_characters_people_confuse() -> None:
    code = new_manual_code()
    assert len(code) == CODE_LENGTH
    assert set(code) <= set(CODE_ALPHABET)
    assert not set("01OIL") & set(CODE_ALPHABET)


def test_qr_token_is_long_and_different_each_time() -> None:
    assert len(new_qr_token()) >= 32
    assert new_qr_token() != new_qr_token()


def test_session_closes_at_its_time_or_when_closed() -> None:
    later = NOW + timedelta(minutes=1)
    assert session_is_open(status="open", closes_at=later, now=NOW)
    assert not session_is_open(status="open", closes_at=NOW, now=NOW)
    assert not session_is_open(status="closed", closes_at=later, now=NOW)
    assert not session_is_open(status="open", closes_at=None, now=NOW)


@pytest.mark.parametrize(
    ("moment", "term"),
    [
        (datetime(2026, 1, 1, tzinfo=UTC), "2026-H1"),
        (datetime(2026, 6, 30, 16, 59, tzinfo=UTC), "2026-H1"),
        # Already July 1st in Vietnam.
        (datetime(2026, 6, 30, 17, 0, tzinfo=UTC), "2026-H2"),
        (datetime(2026, 12, 31, 16, 59, tzinfo=UTC), "2026-H2"),
        # Already the next year in Vietnam.
        (datetime(2026, 12, 31, 17, 0, tzinfo=UTC), "2027-H1"),
    ],
)
def test_term_uses_vietnam_time(moment: datetime, term: str) -> None:
    assert term_of(moment) == term


def test_duration_in_hours() -> None:
    assert duration_hours(NOW, NOW + timedelta(minutes=90)) == Decimal("1.50")
    assert duration_hours(NOW, NOW + timedelta(minutes=20)) == Decimal("0.33")
    assert duration_hours(NOW, NOW) == Decimal("0.00")
    assert duration_hours(None, NOW) == Decimal("0.00")


@pytest.mark.parametrize(
    ("base", "multiplier", "cap", "used", "expected"),
    [
        ("4", "1", None, "100", "4.00"),
        ("4", "1.5", None, "0", "6.00"),
        ("3", "0.333", None, "0", "1.00"),
        ("4", "1", "10", "0", "4.00"),
        ("4", "1", "10", "8", "2"),
        ("4", "1", "10", "10", "0"),
        ("4", "1", "10", "12", "0"),
    ],
)
def test_apply_rule(
    base: str, multiplier: str, cap: str | None, used: str, expected: str
) -> None:
    result = apply_rule(
        Decimal(base),
        multiplier=Decimal(multiplier),
        cap=Decimal(cap) if cap else None,
        already_in_term=Decimal(used),
    )
    assert result == Decimal(expected)


def test_check_in_needs_exactly_one_input() -> None:
    for body in ({}, {"code": "ABC234", "token": "a" * 32}):
        with pytest.raises(ValidationError) as caught:
            CheckInRequest.model_validate(body)
        assert caught.value.errors()[0]["type"] == "checkin_input_required"


def test_check_in_code_is_trimmed_and_uppercased() -> None:
    assert CheckInRequest(code=" abc234 ").code == "ABC234"


@pytest.mark.parametrize("code", ["ABC", "ABCDEFG", "AB-234", "a\x00b234"])
def test_check_in_rejects_bad_codes(code: str) -> None:
    with pytest.raises(ValidationError):
        CheckInRequest(code=code)


@pytest.mark.parametrize("token", ["short", "x" * 65, "has space in the token here"])
def test_check_in_rejects_bad_tokens(token: str) -> None:
    with pytest.raises(ValidationError):
        CheckInRequest(token=token)


@pytest.mark.parametrize("minutes", [4, 1441])
def test_session_length_limits(minutes: int) -> None:
    with pytest.raises(ValidationError):
        SessionCreateRequest(minutes=minutes)


def test_appeal_needs_a_real_reason() -> None:
    with pytest.raises(ValidationError):
        AppealRequest(reason="abc")
    assert AppealRequest(reason="Toi co mat").reason == "Toi co mat"


def test_adjustment_rejects_zero() -> None:
    with pytest.raises(ValidationError) as caught:
        AdjustmentRequest.model_validate(
            {"user_id": USER_V7, "delta_hours": "0", "reason": "Khong doi"}
        )
    assert caught.value.errors()[0]["type"] == "delta_zero"


def test_adjustment_needs_a_uuid7_user() -> None:
    with pytest.raises(ValidationError) as caught:
        AdjustmentRequest.model_validate(
            {
                "user_id": "9f1f1c2e-3b4a-4c5d-8e6f-7a8b9c0d1e2f",
                "delta_hours": "1",
                "reason": "Sua lai gio",
            }
        )
    assert caught.value.errors()[0]["type"] == "uuid_invalid"


@pytest.mark.parametrize(
    "body",
    [{"multiplier": "0.05"}, {"multiplier": "11"}, {"cap_hours": "0"}],
)
def test_hour_rule_limits(body: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        HourRuleRequest.model_validate(body)
