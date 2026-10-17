"""Domain exceptions mapped to the single {code, message} HTTP envelope."""

from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class DomainError(Exception):
    """Base error carrying a stable English code plus an HTTP status."""

    code = "INTERNAL_ERROR"
    status = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class EmailTakenError(DomainError):
    code = "EMAIL_TAKEN"
    status = 409


class PhoneTakenError(DomainError):
    code = "PHONE_TAKEN"
    status = 409


class InvalidCredentialsError(DomainError):
    code = "INVALID_CREDENTIALS"
    status = 401


class SamePasswordError(DomainError):
    code = "SAME_AS_CURRENT"
    status = 400


class InvalidBusinessProfileError(DomainError):
    code = "INVALID_BUSINESS_PROFILE"
    status = 400


class SlugTakenError(DomainError):
    code = "SLUG_TAKEN"
    status = 409


class TaxCodeTakenError(DomainError):
    code = "TAX_CODE_TAKEN"
    status = 409


class OrgNameTakenError(DomainError):
    code = "NAME_TAKEN"
    status = 409


class OrgDeletedError(DomainError):
    code = "ORG_DELETED"
    status = 410


class UnsupportedMediaError(DomainError):
    code = "UNSUPPORTED_MEDIA"
    status = 415


class InvalidMediaRoleError(DomainError):
    code = "INVALID_MEDIA_ROLE"
    status = 400


class MediaTooLargeError(DomainError):
    code = "MEDIA_TOO_LARGE"
    status = 413


class EmailNotVerifiedError(DomainError):
    code = "EMAIL_NOT_VERIFIED"
    status = 403


class InvalidCodeError(DomainError):
    code = "INVALID_CODE"
    status = 400


class ExpiredCodeError(DomainError):
    code = "CODE_EXPIRED"
    status = 410


class TooManyRequestsError(DomainError):
    code = "TOO_MANY_REQUESTS"
    status = 429


class ServerOverloadedError(DomainError):
    code = "SERVER_OVERLOADED"
    status = 503


class NotFoundError(DomainError):
    code = "NOT_FOUND"
    status = 404


class UnauthorizedError(DomainError):
    code = "UNAUTHORIZED"
    status = 401


class ForbiddenError(DomainError):
    code = "FORBIDDEN"
    status = 403


class AccountSuspendedError(DomainError):
    code = "ACCOUNT_SUSPENDED"
    status = 403


class UserNotFoundError(DomainError):
    code = "USER_NOT_FOUND"
    status = 404


class AlreadyMemberError(DomainError):
    code = "ALREADY_MEMBER"
    status = 409


class AlreadyInvitedError(DomainError):
    code = "ALREADY_INVITED"
    status = 409


class MemberNotFoundError(DomainError):
    code = "MEMBER_NOT_FOUND"
    status = 404


class OwnerImmutableError(DomainError):
    code = "OWNER_IMMUTABLE"
    status = 400


class InvalidMemberStateError(DomainError):
    code = "INVALID_MEMBER_STATE"
    status = 400


class InviteOnlyError(DomainError):
    code = "INVITE_ONLY"
    status = 403


class InvalidRoleError(DomainError):
    code = "INVALID_ROLE"
    status = 400


class RoleNameTakenError(DomainError):
    code = "ROLE_NAME_TAKEN"
    status = 409


class RoleNotFoundError(DomainError):
    code = "ROLE_NOT_FOUND"
    status = 404


class InvalidOrgStateError(DomainError):
    code = "INVALID_ORG_STATE"
    status = 400


class SkillNotFoundError(DomainError):
    code = "SKILL_NOT_FOUND"
    status = 404


class InvalidSkillLevelError(DomainError):
    code = "INVALID_SKILL_LEVEL"
    status = 400


class TooManyContactsError(DomainError):
    code = "TOO_MANY_CONTACTS"
    status = 400


class ProfileNotFoundError(DomainError):
    code = "PROFILE_NOT_FOUND"
    status = 404


class AlreadyRegisteredError(DomainError):
    code = "ALREADY_REGISTERED"
    status = 409


class RegistrationClosedError(DomainError):
    code = "REGISTRATION_CLOSED"
    status = 400


class AlreadyCheckedInError(DomainError):
    code = "ALREADY_CHECKED_IN"
    status = 409


class InvalidRegistrationStateError(DomainError):
    code = "INVALID_REGISTRATION_STATE"
    status = 400


class InvalidHoursStateError(DomainError):
    code = "INVALID_HOURS_STATE"
    status = 400


class CertificateExistsError(DomainError):
    code = "CERTIFICATE_EXISTS"
    status = 409


class ReviewExistsError(DomainError):
    code = "REVIEW_EXISTS"
    status = 409


class InvalidPostStateError(DomainError):
    code = "INVALID_POST_STATE"
    status = 400


class ChatContentRequiredError(DomainError):
    code = "CHAT_CONTENT_REQUIRED"
    status = 400


class PostContentRequiredError(DomainError):
    code = "POST_CONTENT_REQUIRED"
    status = 400


class PostTitleRequiredError(DomainError):
    code = "POST_TITLE_REQUIRED"
    status = 400


class ChannelNotFoundError(DomainError):
    code = "CHANNEL_NOT_FOUND"
    status = 404


class ChannelNameTakenError(DomainError):
    code = "CHANNEL_NAME_TAKEN"
    status = 409


class ChannelArchivedError(DomainError):
    code = "CHANNEL_ARCHIVED"
    status = 409


class InvalidChannelStateError(DomainError):
    code = "INVALID_CHANNEL_STATE"
    status = 400


async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    """Render every domain failure as {"code": ..., "message": ...}."""
    return JSONResponse(
        status_code=exc.status, content={"code": exc.code, "message": exc.message}
    )


def validation_message(errors: list[dict]) -> str:
    """First pydantic error as 'field: reason' for API consumers."""
    if not errors:
        return "Request validation failed."
    first = errors[0]
    loc = ".".join(
        str(part) for part in first.get("loc", ()) if part != "body"
    )
    message = first.get("msg", "Invalid value.")
    return f"{loc}: {message}" if loc else message


async def validation_error_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    """Reshape pydantic 422s into the shared {code, message} envelope."""
    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "message": validation_message(exc.errors()),
        },
    )


async def http_error_handler(
    _: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Same envelope for stray HTTP errors (unknown routes, 405s)."""
    code = "NOT_FOUND" if exc.status_code == 404 else "REQUEST_FAILED"
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": code, "message": message},
        headers=getattr(exc, "headers", None),
    )
