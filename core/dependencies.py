"""FastAPI Depends wiring: interfaces to implementations (DIP root)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.config import Settings, get_settings
from core.email import EmailSender, build_sender
from core.exceptions import AccountSuspendedError, UnauthorizedError
from core.security import AuthTokenError, decode_access_token

if TYPE_CHECKING:
    from auth.service import AuthService

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    """Authenticated identity handed to routers (no driver models)."""

    id: UUID
    email: str
    status: str


def get_auth_service(
    settings: Settings = Depends(get_settings),
) -> AuthService:
    """Build one AuthService per request from concrete ports."""
    from auth.repository import (
        Argon2PasswordHasher,
        CqlPasswordResetStore,
        CqlRateLimiter,
        CqlRefreshTokenStore,
        CqlUserRepository,
        CqlVerificationCodeStore,
    )
    from auth.service import AuthService

    mailer: EmailSender = build_sender(
        settings.smtp_host,
        settings.smtp_port,
        settings.smtp_username,
        settings.smtp_password,
        settings.mail_from,
    )
    return AuthService(
        users=CqlUserRepository(settings.scylla_keyspace),
        refresh_tokens=CqlRefreshTokenStore(),
        verifications=CqlVerificationCodeStore(),
        resets=CqlPasswordResetStore(),
        limiter=CqlRateLimiter(settings.scylla_keyspace),
        hasher=Argon2PasswordHasher(),
        mailer=mailer,
        settings=settings,
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    """Validate the Bearer JWT and load an active user for the request."""
    from auth.repository import CqlUserRepository

    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Authentication required.")
    try:
        payload = decode_access_token(credentials.credentials, settings.jwt_secret)
    except AuthTokenError as exc:
        raise UnauthorizedError("Session has expired.") from exc
    try:
        user_id = UUID(str(payload["sub"]))
    except ValueError as exc:
        raise UnauthorizedError("Session has expired.") from exc
    user = CqlUserRepository(settings.scylla_keyspace).get_by_id(user_id)
    if user is None:
        raise UnauthorizedError("Session has expired.")
    if user.status != "active":
        raise AccountSuspendedError("Account is suspended.")
    return CurrentUser(id=user.id, email=user.email, status=user.status)
