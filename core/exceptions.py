"""Domain exceptions mapped to the single {code, message} HTTP envelope."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


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


async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    """Render every domain failure as {"code": ..., "message": ...}."""
    return JSONResponse(
        status_code=exc.status, content={"code": exc.code, "message": exc.message}
    )
