"""FastAPI dependencies shared by the account routes."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.auth.errors import api_error, unauthorized
from src.auth.mailer import Mailer, get_mailer
from src.auth.tokens import InvalidAccessTokenError, decode_access_token
from src.config import AuthSettings, get_auth_settings
from src.models.auth import AuthSession, User

USER_AGENT_MAX_LENGTH = 512

_bearer = HTTPBearer(auto_error=False)


def get_db(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as db:
        yield db


@dataclass(frozen=True)
class ClientInfo:
    ip: str
    user_agent: str | None


def get_client_info(request: Request) -> ClientInfo:
    user_agent = request.headers.get("user-agent")
    return ClientInfo(
        ip=request.client.host if request.client else "unknown",
        user_agent=user_agent[:USER_AGENT_MAX_LENGTH] if user_agent else None,
    )


Db = Annotated[Session, Depends(get_db)]
Client = Annotated[ClientInfo, Depends(get_client_info)]
Config = Annotated[AuthSettings, Depends(get_auth_settings)]
MailerDep = Annotated[Mailer, Depends(get_mailer)]


@dataclass(frozen=True)
class Principal:
    user: User
    session: AuthSession


def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Db,
    settings: Config,
) -> Principal:
    """Resolve the bearer token, so a revoked session stops working immediately."""
    if credentials is None:
        raise unauthorized("not_authenticated")
    try:
        claims = decode_access_token(credentials.credentials, settings.jwt_secret)
    except InvalidAccessTokenError as exc:
        raise unauthorized("invalid_token") from exc

    session = db.get(AuthSession, claims.session_id)
    user = db.get(User, claims.user_id)
    if session is None or user is None or session.user_id != user.id:
        raise unauthorized("invalid_token")
    expired = session.expires_at is not None and session.expires_at <= datetime.now(UTC)
    if session.revoked_at is not None or expired:
        raise unauthorized("session_revoked")
    if user.status != "active":
        raise api_error(status.HTTP_403_FORBIDDEN, "account_disabled")
    return Principal(user=user, session=session)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def get_optional_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Db,
    settings: Config,
) -> Principal | None:
    """Treat a missing or stale token as an anonymous visitor on public routes."""
    if credentials is None:
        return None
    try:
        return get_principal(credentials, db, settings)
    except HTTPException:
        return None


OptionalPrincipal = Annotated[Principal | None, Depends(get_optional_principal)]
