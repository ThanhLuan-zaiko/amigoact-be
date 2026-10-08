"""Pydantic request/response DTOs for auth (validation lives here)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

_PASSWORD_RULE = "8+ chars with upper, lower, digit and special character."
_PHONE_PATTERN = re.compile(r"^0(?:3|5|7|8|9)\d{8}$")
_EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_SPECIAL_PATTERN = re.compile(r"[^A-Za-z0-9]")


def _reject_fake_phone(digits: str) -> bool:
    """Detect all-identical or strictly sequential digit runs."""
    if len(set(digits)) == 1:
        return True
    ascending = all(int(digits[i + 1]) - int(digits[i]) == 1 for i in range(9))
    descending = all(int(digits[i]) - int(digits[i + 1]) == 1 for i in range(9))
    return ascending or descending


def validate_password(value: str) -> str:
    """Shared password policy: length plus four character classes."""
    if (
        len(value) < 8
        or not re.search(r"[A-Z]", value)
        or not re.search(r"[a-z]", value)
        or not re.search(r"[0-9]", value)
        or not _SPECIAL_PATTERN.search(value)
    ):
        raise ValueError(f"Password must have {_PASSWORD_RULE}")
    return value


def validate_phone(value: str) -> str:
    """Shared Vietnam mobile policy: prefix range plus anti-fake check."""
    number = re.sub(r"[\s.]", "", value)
    if not _PHONE_PATTERN.match(number):
        raise ValueError("Phone must be a valid Vietnam mobile number.")
    if _reject_fake_phone(number):
        raise ValueError("Phone number looks invalid.")
    return number


def validate_email(value: str) -> str:
    """Shared email shape check, normalized to lowercase."""
    address = value.strip().lower()
    if len(address) > 254 or not _EMAIL_PATTERN.match(address):
        raise ValueError("Email address is invalid.")
    return address


class RegisterRequest(BaseModel):
    """Account creation payload. Every field is required."""

    email: str
    phone: str
    password: str
    full_name: Annotated[str, Field(min_length=2, max_length=100)]

    _email = field_validator("email", mode="before")(validate_email)  # noqa: SLF001
    _phone = field_validator("phone", mode="before")(validate_phone)  # noqa: SLF001
    _password = field_validator("password", mode="before")(validate_password)  # noqa: SLF001

    @field_validator("full_name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class LoginRequest(BaseModel):
    """Credential payload. Failure reasons stay generic downstream."""

    email: str
    password: Annotated[str, Field(min_length=1, max_length=256)]

    _email = field_validator("email", mode="before")(validate_email)  # noqa: SLF001


class VerifyEmailRequest(BaseModel):
    """Consume a verification code for an email address."""

    email: str
    code: Annotated[str, Field(pattern=r"^\d{6}$")]

    _email = field_validator("email", mode="before")(validate_email)  # noqa: SLF001


class ResendVerificationRequest(BaseModel):
    """Reissue a verification code. Response never reveals existence."""

    email: str

    _email = field_validator("email", mode="before")(validate_email)  # noqa: SLF001


class ForgotPasswordRequest(BaseModel):
    """Request a reset code. Response never reveals existence."""

    email: str

    _email = field_validator("email", mode="before")(validate_email)  # noqa: SLF001


class ResetPasswordRequest(BaseModel):
    """Consume a reset code and set a fresh password."""

    email: str
    code: Annotated[str, Field(pattern=r"^\d{6}$")]
    new_password: str

    _email = field_validator("email", mode="before")(validate_email)  # noqa: SLF001
    _password = field_validator("new_password", mode="before")(validate_password)  # noqa: SLF001


class ChangePasswordRequest(BaseModel):
    """Authenticated rotation. Requires proof of the current password."""

    current_password: Annotated[str, Field(min_length=1, max_length=256)]
    new_password: str

    _password = field_validator("new_password", mode="before")(validate_password)  # noqa: SLF001


class DevChallengeRequest(BaseModel):
    """Dev-only code issuance (ENV=dev). kind is verification or reset."""

    email: str
    kind: Annotated[str, Field(pattern="^(verification|reset)$")] = "verification"

    _email = field_validator("email", mode="before")(validate_email)  # noqa: SLF001


class TokenResponse(BaseModel):
    """Short-lived access token returned after login or refresh."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int


class UserProfile(BaseModel):
    """Public session profile. Never includes hashes or tokens."""

    id: UUID
    email: str
    phone: str
    full_name: str
    email_verified: bool
    created_at: datetime


class AcceptedResponse(BaseModel):
    """Generic acknowledgement that reveals nothing about account existence."""

    accepted: bool = True


class DevChallengeResponse(BaseModel):
    """Dev-only plaintext code. Never exposed outside ENV=dev."""

    email: str
    kind: str
    code: str
    expires_in_seconds: int
