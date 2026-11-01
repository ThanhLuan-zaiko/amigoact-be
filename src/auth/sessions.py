"""Login sessions and rotation of refresh tokens.

Each session owns one family of refresh tokens: family_id equals session_id.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.auth.deps import ClientInfo
from src.auth.errors import unauthorized
from src.auth.schemas import TokenResponse
from src.auth.tokens import create_access_token, hash_opaque_token, new_opaque_token
from src.config import AuthSettings
from src.models.auth import AuthRefreshToken, AuthSession, User

# Parallel requests can present the same token just after it rotated. Inside this
# window that is not treated as theft, so one browser does not log itself out.
REFRESH_REUSE_GRACE = timedelta(seconds=10)


def _issue_tokens(
    db: Session,
    user_id: uuid.UUID,
    session: AuthSession,
    settings: AuthSettings,
    rotated_from: str | None = None,
) -> TokenResponse:
    access_ttl = timedelta(minutes=settings.access_token_minutes)
    refresh_ttl = timedelta(days=settings.refresh_token_days)
    expires_at = datetime.now(UTC) + refresh_ttl
    raw_token = new_opaque_token()
    db.add(
        AuthRefreshToken(
            token_hash=hash_opaque_token(raw_token),
            user_id=user_id,
            family_id=session.session_id,
            expires_at=expires_at,
            rotated_from=rotated_from,
        )
    )
    session.expires_at = expires_at
    return TokenResponse(
        access_token=create_access_token(
            user_id, session.session_id, settings.jwt_secret, access_ttl
        ),
        refresh_token=raw_token,
        expires_in=int(access_ttl.total_seconds()),
        refresh_expires_in=int(refresh_ttl.total_seconds()),
    )


def start_session(
    db: Session, user: User, settings: AuthSettings, client: ClientInfo
) -> TokenResponse:
    """Create a session and its first tokens. The caller commits."""
    now = datetime.now(UTC)
    session = AuthSession(
        session_id=uuid.uuid7(),
        user_id=user.id,
        user_agent=client.user_agent,
        ip=client.ip,
        last_seen_at=now,
    )
    db.add(session)
    db.flush()
    user.last_login_at = now
    return _issue_tokens(db, user.id, session, settings)


def rotate_refresh_token(
    db: Session, raw_token: str, settings: AuthSettings
) -> TokenResponse:
    now = datetime.now(UTC)
    token_hash = hash_opaque_token(raw_token)
    token = db.scalar(
        select(AuthRefreshToken)
        .where(AuthRefreshToken.token_hash == token_hash)
        .with_for_update()
    )
    if token is None or token.expires_at <= now:
        raise unauthorized("invalid_refresh_token")

    session = db.get(AuthSession, token.family_id)
    user = db.get(User, token.user_id)
    if (
        session is None
        or session.revoked_at is not None
        or user is None
        or user.status != "active"
    ):
        raise unauthorized("invalid_refresh_token")

    if token.revoked_at is None:
        token.revoked_at = now
    elif now - token.revoked_at > REFRESH_REUSE_GRACE:
        # A rotated token came back: assume it was stolen and end the whole session.
        revoke_session(db, session)
        db.commit()
        raise unauthorized("refresh_token_reused")

    session.last_seen_at = now
    tokens = _issue_tokens(db, user.id, session, settings, rotated_from=token_hash)
    db.commit()
    return tokens


def revoke_session(db: Session, session: AuthSession) -> None:
    """End one session and its refresh tokens. The caller commits."""
    now = datetime.now(UTC)
    session.revoked_at = now
    db.execute(
        update(AuthRefreshToken)
        .where(
            AuthRefreshToken.family_id == session.session_id,
            AuthRefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )


def revoke_user_sessions(
    db: Session, user_id: uuid.UUID, keep_session_id: uuid.UUID | None = None
) -> None:
    """End every active session of a user, except one if given. The caller commits."""
    statement = select(AuthSession).where(
        AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
    )
    if keep_session_id is not None:
        statement = statement.where(AuthSession.session_id != keep_session_id)
    for session in db.scalars(statement).all():
        revoke_session(db, session)


def list_active_sessions(db: Session, user_id: uuid.UUID) -> list[AuthSession]:
    now = datetime.now(UTC)
    statement = (
        select(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
        .order_by(AuthSession.created_at.desc())
    )
    return list(db.scalars(statement))
