"""FastAPI Depends wiring: interfaces to implementations (DIP root)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.config import Settings, get_settings
from core.email import EmailSender, build_sender
from core.exceptions import AccountSuspendedError, UnauthorizedError
from core.security import AuthTokenError, decode_access_token

if TYPE_CHECKING:
    from apikeys.service import ApiKeyService
    from auth.service import AuthService
    from auth.session_service import SessionService
    from core.guard import EdgeGuard
    from core.realtime import ConnectionManager
    from notifications.service import NotificationService
    from orgs.interfaces import UserDirectory
    from orgs.media_service import MediaService
    from orgs.member_service import MemberService
    from orgs.service import OrgService
    from rbac.interfaces import AccessControl
    from rbac.roles_service import OrgRoleService

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
    from auth.session_repository import CqlSessionStore
    from auth.service import AuthService
    from orgs.media_repository import CqlMediaRepository

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
        media=CqlMediaRepository(),
        sessions=CqlSessionStore(),
    )


def get_session_service() -> "SessionService":
    """Build one SessionService per request."""
    from auth.repository import CqlRefreshTokenStore
    from auth.session_repository import CqlSessionStore
    from auth.session_service import SessionService

    return SessionService(
        sessions=CqlSessionStore(),
        refresh_tokens=CqlRefreshTokenStore(),
    )


def get_api_key_service() -> "ApiKeyService":
    """Build one ApiKeyService per request."""
    from apikeys.repository import CqlApiKeyStore
    from apikeys.service import ApiKeyService
    from orgs.repository import CqlOrgRepository

    return ApiKeyService(
        store=CqlApiKeyStore(),
        orgs=CqlOrgRepository(),
        access=get_access_control(),
    )


def get_access_control() -> AccessControl:
    """Build one AccessControlService per request over the rbac tables."""
    from rbac.repository import (
        CqlAuditWriter,
        CqlGrantRepository,
        CqlRoleRepository,
    )
    from rbac.service import AccessControlService

    return AccessControlService(
        roles=CqlRoleRepository(),
        grants=CqlGrantRepository(),
        audit=CqlAuditWriter(),
    )


def get_org_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> OrgService:
    """Build one OrgService per request from the org repository."""
    from orgs.directory_events import WsOrgDirectoryEvents
    from orgs.media_repository import CqlMediaRepository
    from orgs.repository import CqlOrgRepository
    from orgs.service import OrgService

    return OrgService(
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        media=CqlMediaRepository(),
        store=get_media_store(settings),
        events=WsOrgDirectoryEvents(
            getattr(request.app.state, "ws_manager", None)
        ),
        access=access,
    )


def get_media_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> MediaService:
    """Build one MediaService per request for the org gallery."""
    from admin.repository import CqlModerationStore
    from orgs.directory_events import WsOrgDirectoryEvents
    from orgs.media_service import MediaService
    from orgs.media_repository import CqlMediaRepository
    from orgs.repository import CqlOrgRepository

    return MediaService(
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        media=CqlMediaRepository(),
        store=get_media_store(settings),
        max_image_bytes=settings.media_max_image_mb * 1024 * 1024,
        max_video_bytes=settings.media_max_video_mb * 1024 * 1024,
        access=access,
        events=WsOrgDirectoryEvents(
            getattr(request.app.state, "ws_manager", None)
        ),
        moderation=CqlModerationStore(),
    )


def get_notification_service(request: Request) -> NotificationService:
    """Build one NotificationService per request over both tables."""
    from notifications.interfaces import NotificationPublisher
    from notifications.repository import (
        CqlNotificationStore,
        CqlPreferenceStore,
    )
    from notifications.service import NotificationService

    class _WsPublisher(NotificationPublisher):
        """Fan notifications onto the socket registry (best-effort)."""

        def __init__(self, manager: ConnectionManager | None) -> None:
            self._manager = manager

        def push(self, user_id: UUID, payload: dict) -> None:
            if self._manager is not None:
                self._manager.schedule_publish(
                    f"notifications:{user_id}", payload
                )

    return NotificationService(
        CqlNotificationStore(),
        _WsPublisher(getattr(request.app.state, "ws_manager", None)),
        CqlPreferenceStore(),
    )


def user_directory(settings: Settings) -> UserDirectory:
    """Read-only bridge onto the auth user tables (shared by features)."""
    from auth.repository import CqlUserRepository
    from orgs.interfaces import UserBrief, UserDirectory

    class _UserDirectory(UserDirectory):
        """get_brief/find_by_email delegate to the auth repository."""

        def __init__(self) -> None:
            self._users = CqlUserRepository(settings.scylla_keyspace)

        def _brief(self, user) -> UserBrief | None:  # noqa: ANN001
            if user is None:
                return None
            return UserBrief(
                id=user.id,
                full_name=user.full_name,
                email=user.email,
                status=user.status,
                avatar_media_id=getattr(user, "avatar_media_id", None),
                last_seen_at=getattr(user, "last_seen_at", None),
            )

        def get_brief(self, user_id: UUID) -> UserBrief | None:
            return self._brief(self._users.get_by_id(user_id))

        def find_by_email(self, email: str) -> UserBrief | None:
            return self._brief(self._users.get_by_email(email))

    return _UserDirectory()


def get_member_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
    notifications: NotificationService = Depends(get_notification_service),
) -> MemberService:
    """Build one MemberService; user lookup adapts the auth repository."""
    from orgs.media_repository import CqlMediaRepository
    from orgs.member_events import WsMemberEvents
    from orgs.member_repository import CqlMemberRepository
    from orgs.member_service import MemberService
    from orgs.repository import CqlOrgRepository
    from profiles.repository import CqlProfileStore

    return MemberService(
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        members=CqlMemberRepository(),
        users=user_directory(settings),
        access=access,
        events=WsMemberEvents(
            getattr(request.app.state, "ws_manager", None)
        ),
        notifications=notifications,
        profiles=CqlProfileStore(),
        media=CqlMediaRepository(),
    )


def get_role_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> OrgRoleService:
    """Build one OrgRoleService per request for org role CRUD."""
    from orgs.member_events import WsMemberEvents
    from orgs.member_repository import CqlMemberRepository
    from orgs.repository import CqlOrgRepository
    from rbac.repository import CqlRoleRepository
    from rbac.roles_service import OrgRoleService

    return OrgRoleService(
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        members=CqlMemberRepository(),
        roles=CqlRoleRepository(),
        access=access,
        events=WsMemberEvents(
            getattr(request.app.state, "ws_manager", None)
        ),
    )


def build_edge_guard(settings: Settings) -> EdgeGuard:
    """Wire the process-wide edge guard to the ScyllaDB counter store."""
    from auth.repository import CqlRateLimiter
    from core.guard import EdgeGuard, GuardPolicy

    return EdgeGuard(
        GuardPolicy.from_settings(settings),
        CqlRateLimiter(settings.scylla_keyspace).hit,
    )


def get_media_store(settings: Settings = Depends(get_settings)) -> LocalMediaStore:
    """Single local-disk backend rooted at MEDIA_ROOT (cloud later)."""
    from core.media import LocalMediaStore

    return LocalMediaStore(settings.media_root)


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


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> CurrentUser | None:
    """Like get_current_user but returns None for anonymous visitors."""
    if credentials is None or not credentials.credentials:
        return None
    try:
        return get_current_user(credentials, settings)
    except UnauthorizedError:
        return None
