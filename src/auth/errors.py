"""API errors. The detail is a stable code that clients translate for users."""

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError


def api_error(
    status_code: int, code: str, headers: dict[str, str] | None = None
) -> HTTPException:
    return HTTPException(status_code=status_code, detail=code, headers=headers)


def unauthorized(code: str) -> HTTPException:
    return api_error(status.HTTP_401_UNAUTHORIZED, code, {"WWW-Authenticate": "Bearer"})


def conflict_from_integrity_error(exc: IntegrityError) -> HTTPException:
    """Map a unique violation on users to the code of the field that collided."""
    message = str(exc.orig)
    if "users_email_uq" in message:
        return api_error(status.HTTP_409_CONFLICT, "email_taken")
    if "users_phone_uq" in message:
        return api_error(status.HTTP_409_CONFLICT, "phone_taken")
    return api_error(status.HTTP_409_CONFLICT, "conflict")
