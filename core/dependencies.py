"""FastAPI Depends wiring: interfaces to implementations (DIP root)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import Depends, WebSocket
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.config import Settings, get_settings
from core.email import EmailSender, build_sender
from core.exceptions import AccountSuspendedError, UnauthorizedError
from core.security import AuthTokenError, decode_access_token

if TYPE_CHECKING:
    from auth.service import AuthService
    from core.realtime import ConnectionManager
    from orgs.service import OrgService
    from realtime.service import RealtimeService

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


def get_org_service(
    settings: Settings = Depends(get_settings),
) -> OrgService:
    """Build one OrgService per request from the org repository."""
    from core.media import LocalMediaStore
    from orgs.repository import CqlMediaRepository, CqlOrgRepository
    from orgs.service import OrgService

    return OrgService(
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        media=CqlMediaRepository(),
        store=get_media_store(settings),
        max_image_bytes=settings.media_max_image_mb * 1024 * 1024,
        max_video_bytes=settings.media_max_video_mb * 1024 * 1024,
    )


def get_media_store(settings: Settings = Depends(get_settings)) -> LocalMediaStore:
    """Single local-disk backend rooted at MEDIA_ROOT (cloud later)."""
    from core.media import LocalMediaStore

    return LocalMediaStore(settings.media_root)


def get_connection_manager(websocket: WebSocket) -> ConnectionManager:
    """App-scoped ephemeral socket registry initialized in lifespan."""
    manager = getattr(websocket.app.state, "ws_manager", None)
    if manager is None:
        raise RuntimeError("WebSocket manager is not initialized.")
    return manager


def get_realtime_service(
    settings: Settings = Depends(get_settings),
) -> RealtimeService:
    """Build one RealtimeService per ticket/socket request."""
    from orgs.repository import CqlOrgRepository
    from realtime.interfaces import OrgMembership
    from realtime.repository import CqlWsTicketStore
    from realtime.service import RealtimeService

    class _OrgMembership(OrgMembership):
        """Channel ACL reads delegate to the orgs membership table."""

        def __init__(self, orgs: CqlOrgRepository) -> None:
            self._orgs = orgs

        def is_member(self, org_id: UUID, user_id: UUID) -> bool:
            return self._orgs.is_member(org_id, user_id)

    orgs = CqlOrgRepository(settings.scylla_keyspace)
    return RealtimeService(
        tickets=CqlWsTicketStore(settings.scylla_keyspace),
        membership=_OrgMembership(orgs),
        attendance=None,
        ticket_ttl_seconds=settings.ws_ticket_ttl_seconds,
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
