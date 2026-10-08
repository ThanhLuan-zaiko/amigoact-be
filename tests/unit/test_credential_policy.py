"""Unit tests for credential policy validators (no I/O)."""

import pytest
from pydantic import ValidationError

from auth.schemas import (
    RegisterRequest,
    ResetPasswordRequest,
    validate_email,
    validate_password,
    validate_phone,
)

VALID_PASSWORD = "Aa1!secure"
VALID_PHONE = "0912345678"
VALID_EMAIL = "Student@Example.com"


def _register(**overrides: object) -> RegisterRequest:
    payload: dict[str, object] = {
        "email": "student@example.com",
        "phone": VALID_PHONE,
        "password": VALID_PASSWORD,
        "full_name": "Nguyen Van A",
    }
    payload.update(overrides)
    return RegisterRequest(**payload)  # type: ignore[arg-type]


def test_password_accepts_all_four_classes() -> None:
    assert validate_password(VALID_PASSWORD) == VALID_PASSWORD


@pytest.mark.parametrize(
    "weak",
    ["short1!", "alllowercase1!", "ALLUPPERCASE1!", "NoDigitsHere!", "NoSpecial123"],
)
def test_password_rejects_missing_class(weak: str) -> None:
    with pytest.raises(ValueError):
        validate_password(weak)


@pytest.mark.parametrize(
    "phone",
    ["0912345678", "0312345678", "0523456789", "0777777779", "0898765432"],
)
def test_phone_accepts_valid_prefixes(phone: str) -> None:
    assert validate_phone(phone) == phone


@pytest.mark.parametrize(
    "phone",
    [
        "0123456789",  # strictly sequential run
        "9876543210",  # descending run
        "0000000000",  # identical digits
        "1111111111",  # identical digits
        "0212345678",  # invalid prefix
        "091234567",  # too short
        "09123456789",  # too long
    ],
)
def test_phone_rejects_fake_or_malformed(phone: str) -> None:
    with pytest.raises(ValueError):
        validate_phone(phone)


def test_email_normalizes_to_lowercase() -> None:
    assert validate_email(VALID_EMAIL) == "student@example.com"


def test_register_strips_full_name() -> None:
    assert _register(full_name="  Nguyen Van A  ").full_name == "Nguyen Van A"


def test_register_rejects_weak_password_with_422_shape() -> None:
    with pytest.raises(ValidationError):
        _register(password="weak")


def test_reset_password_validates_new_password() -> None:
    with pytest.raises(ValidationError):
        ResetPasswordRequest(
            email="student@example.com", code="123456", new_password="weak"
        )
