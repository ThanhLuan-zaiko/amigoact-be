import pytest
from pydantic import ValidationError
from pydantic_core import PydanticCustomError

from src.auth.schemas import ProfileUpdateRequest, RegisterRequest
from src.auth.validators import (
    check_password_strength,
    has_required_characters,
    is_common_password,
    normalize_legal_id,
    normalize_phone,
    normalize_tax_code,
    password_is_personal,
)

BASE = {"email": "a@example.com", "password": "Long-enough-1", "full_name": "A"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0912345678", "+84912345678"),
        ("091 234 5678", "+84912345678"),
        ("0912.345.678", "+84912345678"),
        ("84912345678", "+84912345678"),
        ("+84912345678", "+84912345678"),
        ("(024) 3825 1234", "+842438251234"),
        ("+1 415 555 2671", "+14155552671"),
    ],
)
def test_normalize_phone(value: str, expected: str) -> None:
    assert normalize_phone(value) == expected


@pytest.mark.parametrize(
    "value", ["abc", "12345678", "091234", "+8491234", "+0123456789", "0912345678901"]
)
def test_normalize_phone_rejects_bad_numbers(value: str) -> None:
    with pytest.raises(PydanticCustomError):
        normalize_phone(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0101234567", "0101234567"),
        ("0101234567-001", "0101234567-001"),
        ("0101234567001", "0101234567-001"),
    ],
)
def test_normalize_tax_code(value: str, expected: str) -> None:
    assert normalize_tax_code(value) == expected


@pytest.mark.parametrize("value", ["123", "01012345678", "010123456-001", "abcdefghij"])
def test_normalize_tax_code_rejects_bad_codes(value: str) -> None:
    with pytest.raises(PydanticCustomError):
        normalize_tax_code(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("001099012345", "001099012345"),
        ("123456789", "123456789"),
        ("b1234567", "B1234567"),
    ],
)
def test_normalize_legal_id(value: str, expected: str) -> None:
    assert normalize_legal_id(value) == expected


@pytest.mark.parametrize("value", ["1234567890", "12345", "ABC 123", "AB-12345"])
def test_normalize_legal_id_rejects_bad_ids(value: str) -> None:
    with pytest.raises(PydanticCustomError):
        normalize_legal_id(value)


@pytest.mark.parametrize(
    "password",
    [
        "password",
        "Password123!",
        "matkhau123",
        "QWERTY12345",
        "12345678",
        "87654321",
        "abcdefgh",
        "aaaaaaaa",
        "12341234",
        "abcabcabc",
    ],
)
def test_common_passwords_are_detected(password: str) -> None:
    assert is_common_password(password)


@pytest.mark.parametrize(
    "password", ["correct horse battery", "A-brand-new-Passw0rd", "T7#kP2vLq9"]
)
def test_uncommon_passwords_are_accepted(password: str) -> None:
    assert not is_common_password(password)


@pytest.mark.parametrize(
    "password",
    ["T7#kP2vLq9", "Ab1!abcd", "Tr00e1i-C00e2y-7", "With Space 1"],
)
def test_password_with_every_character_class_is_accepted(password: str) -> None:
    assert has_required_characters(password)
    assert check_password_strength(password) == password


@pytest.mark.parametrize(
    "password", ["lowercase1!", "UPPERCASE1!", "NoDigits!!", "NoSpecial12"]
)
def test_password_missing_a_character_class_is_rejected(password: str) -> None:
    assert not has_required_characters(password)
    with pytest.raises(PydanticCustomError) as caught:
        check_password_strength(password)
    assert caught.value.type == "password_too_weak"


def test_common_password_with_every_class_is_still_rejected() -> None:
    with pytest.raises(PydanticCustomError) as caught:
        check_password_strength("Password123!")
    assert caught.value.type == "password_common"


def test_password_with_personal_parts_is_detected() -> None:
    email, name = "minh.anh@example.com", "Nguyen Minh Anh"
    assert password_is_personal("minh.anh2000", email, name)
    assert password_is_personal("xxNguyenMinhAnhxx", email, name)
    assert not password_is_personal("correct horse battery", email, name)


def test_short_email_name_is_not_treated_as_personal() -> None:
    assert not password_is_personal("A-brand-new-Passw0rd", "an@example.com", "An")


def errors_of(exc: ValidationError) -> dict[str, str]:
    return {str(error["loc"][-1]): error["type"] for error in exc.errors()}


def test_register_reports_each_missing_business_field() -> None:
    with pytest.raises(ValidationError) as caught:
        RegisterRequest.model_validate({**BASE, "account_type": "business"})
    assert errors_of(caught.value) == {
        "tax_code": "required",
        "company_name": "required",
    }


def test_register_reports_personal_password_on_the_password_field() -> None:
    with pytest.raises(ValidationError) as caught:
        RegisterRequest.model_validate(
            {
                "email": "minh.anh@example.com",
                "password": "Minh.anh2000",
                "full_name": "A",
            }
        )
    assert errors_of(caught.value) == {"password": "password_personal"}


def test_profile_update_normalizes_fields() -> None:
    request = ProfileUpdateRequest.model_validate(
        {"phone": "0912345678", "tax_code": "0101234567001", "legal_rep_id": "b1234567"}
    )
    assert request.phone == "+84912345678"
    assert request.tax_code == "0101234567-001"
    assert request.legal_rep_id == "B1234567"


def test_profile_update_rejects_very_old_birth_date() -> None:
    with pytest.raises(ValidationError) as caught:
        ProfileUpdateRequest.model_validate({"date_of_birth": "1899-12-31"})
    assert errors_of(caught.value) == {"date_of_birth": "birth_date_invalid"}
