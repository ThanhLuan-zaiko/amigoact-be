"""Request and response bodies of the account API."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import InitErrorDetails, PydanticCustomError

from src.auth.validators import (
    check_password_strength,
    normalize_legal_id,
    normalize_phone,
    normalize_tax_code,
    password_is_personal,
)

MIN_BIRTH_YEAR = 1900

# The upper bound keeps Argon2id from hashing arbitrarily long input.
NewPassword = Annotated[
    str, Field(min_length=8, max_length=128), AfterValidator(check_password_strength)
]
CurrentPassword = Annotated[str, Field(min_length=1, max_length=128)]
FullName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
Phone = Annotated[str, Field(max_length=30), AfterValidator(normalize_phone)]
TaxCode = Annotated[str, Field(max_length=30), AfterValidator(normalize_tax_code)]
LegalId = Annotated[str, Field(max_length=30), AfterValidator(normalize_legal_id)]
ShortText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
Address = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]
OpaqueToken = Annotated[str, Field(min_length=1, max_length=256)]


def _field_errors(title: str, errors: dict[str, tuple[str, str]]) -> ValidationError:
    """Build an error that points at specific fields from a model validator."""
    return ValidationError.from_exception_data(
        title,
        [
            InitErrorDetails(
                type=PydanticCustomError(code, message),
                loc=(field,),
                input=None,
            )
            for field, (code, message) in errors.items()
        ],
    )


class RegisterRequest(BaseModel):
    email: EmailStr
    password: NewPassword
    full_name: FullName
    phone: Phone | None = None
    account_type: Literal["individual", "business"] = "individual"
    tax_code: TaxCode | None = None
    company_name: ShortText | None = None

    @model_validator(mode="after")
    def check_across_fields(self) -> Self:
        errors: dict[str, tuple[str, str]] = {}
        if self.account_type == "business":
            required = ("Required for business accounts",)
            if not self.tax_code:
                errors["tax_code"] = ("required", *required)
            if not self.company_name:
                errors["company_name"] = ("required", *required)
        if password_is_personal(self.password, self.email, self.full_name):
            errors["password"] = ("password_personal", "Password is too personal")
        if errors:
            raise _field_errors("RegisterRequest", errors)
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: CurrentPassword


class RefreshRequest(BaseModel):
    refresh_token: OpaqueToken


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: OpaqueToken
    new_password: NewPassword


class ChangePasswordRequest(BaseModel):
    current_password: CurrentPassword
    new_password: NewPassword


class VerifyEmailRequest(BaseModel):
    token: OpaqueToken


class ProfileUpdateRequest(BaseModel):
    """Only the fields present in the body change. Null clears an optional field."""

    full_name: FullName | None = None
    phone: Phone | None = None
    date_of_birth: date | None = None
    gender: Literal["male", "female", "other", "unspecified"] | None = None
    address: Address | None = None
    tax_code: TaxCode | None = None
    company_name: ShortText | None = None
    legal_rep_name: ShortText | None = None
    legal_rep_id: LegalId | None = None
    legal_rep_position: ShortText | None = None

    @field_validator("date_of_birth")
    @classmethod
    def check_birth_date(cls, value: date | None) -> date | None:
        if value is not None and not MIN_BIRTH_YEAR <= value.year:
            raise PydanticCustomError("birth_date_invalid", "Birth date is too old")
        if value is not None and value >= date.today():
            raise PydanticCustomError(
                "birth_date_invalid", "Birth date is in the future"
            )
        return value

    @model_validator(mode="after")
    def reject_null_full_name(self) -> Self:
        if "full_name" in self.model_fields_set and self.full_name is None:
            raise _field_errors(
                "ProfileUpdateRequest",
                {"full_name": ("required", "Full name cannot be empty")},
            )
        return self


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    phone: str | None
    full_name: str
    account_type: str
    tax_code: str | None
    company_name: str | None
    legal_rep_name: str | None
    legal_rep_id: str | None
    legal_rep_position: str | None
    date_of_birth: date | None
    gender: str | None
    address: str | None
    email_verified_at: datetime | None
    last_login_at: datetime | None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int


class AuthResponse(BaseModel):
    user: UserResponse
    tokens: TokenResponse


class SessionResponse(BaseModel):
    session_id: uuid.UUID
    user_agent: str | None
    ip: str | None
    created_at: datetime
    last_seen_at: datetime | None
    is_current: bool
