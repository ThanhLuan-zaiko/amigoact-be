"""Routes for registration, login, sessions, and token refresh."""

import uuid

from fastapi import APIRouter, BackgroundTasks, status

from src.auth import accounts, recovery, sessions
from src.auth.deps import Client, Config, CurrentPrincipal, Db, MailerDep
from src.auth.errors import api_error
from src.auth.schemas import (
    AuthResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    SessionResponse,
    TokenResponse,
    UserResponse,
)
from src.models.auth import AuthSession

router = APIRouter(tags=["auth"])


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    db: Db,
    settings: Config,
    client: Client,
    mailer: MailerDep,
    background: BackgroundTasks,
) -> AuthResponse:
    user = accounts.create_user(db, payload, client)
    tokens = sessions.start_session(db, user, settings, client)
    recovery.queue_email_verification(
        db, user, user.email, settings, mailer, background
    )
    return AuthResponse(user=UserResponse.model_validate(user), tokens=tokens)


@router.post("/auth/login")
def login(
    payload: LoginRequest, db: Db, settings: Config, client: Client
) -> AuthResponse:
    user, tokens = accounts.authenticate(
        db, payload.email, payload.password, settings, client
    )
    return AuthResponse(user=UserResponse.model_validate(user), tokens=tokens)


@router.post("/auth/refresh")
def refresh(payload: RefreshRequest, db: Db, settings: Config) -> TokenResponse:
    return sessions.rotate_refresh_token(db, payload.refresh_token, settings)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(principal: CurrentPrincipal, db: Db) -> None:
    sessions.revoke_session(db, principal.session)
    db.commit()


@router.post("/auth/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(principal: CurrentPrincipal, db: Db) -> None:
    sessions.revoke_user_sessions(db, principal.user.id)
    db.commit()


@router.get("/auth/sessions")
def list_sessions(principal: CurrentPrincipal, db: Db) -> list[SessionResponse]:
    return [
        SessionResponse(
            session_id=session.session_id,
            user_agent=session.user_agent,
            ip=session.ip,
            created_at=session.created_at,
            last_seen_at=session.last_seen_at,
            is_current=session.session_id == principal.session.session_id,
        )
        for session in sessions.list_active_sessions(db, principal.user.id)
    ]


@router.delete("/auth/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_session(session_id: uuid.UUID, principal: CurrentPrincipal, db: Db) -> None:
    session = db.get(AuthSession, session_id)
    if session is None or session.user_id != principal.user.id:
        raise api_error(status.HTTP_404_NOT_FOUND, "session_not_found")
    sessions.revoke_session(db, session)
    db.commit()
