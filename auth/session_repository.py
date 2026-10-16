"""cqlengine persistence for auth_sessions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from auth.interfaces import SessionStore
from auth.model import AuthSession


class CqlSessionStore(SessionStore):
    """Session rows keyed by the refresh-token family id."""

    def create(
        self,
        user_id: UUID,
        session_id: UUID,
        device_label: str | None,
        user_agent: str | None,
        ip: str | None,
        expires_at: datetime,
        now: datetime,
    ) -> AuthSession:
        return AuthSession.create(
            user_id=user_id,
            session_id=session_id,
            device_label=device_label,
            user_agent=user_agent,
            ip=ip,
            created_at=now,
            last_seen_at=now,
            expires_at=expires_at,
        )

    def touch(self, user_id: UUID, session_id: UUID, now: datetime) -> None:
        AuthSession.objects(
            user_id=user_id, session_id=session_id
        ).update(last_seen_at=now)

    def list_mine(self, user_id: UUID) -> list[AuthSession]:
        return list(AuthSession.objects(user_id=user_id).all())

    def get(self, user_id: UUID, session_id: UUID) -> AuthSession | None:
        return AuthSession.objects(
            user_id=user_id, session_id=session_id
        ).first()

    def revoke(self, user_id: UUID, session_id: UUID, now: datetime) -> None:
        AuthSession.objects(
            user_id=user_id, session_id=session_id
        ).update(revoked_at=now)

    def revoke_all(self, user_id: UUID, now: datetime) -> None:
        for row in AuthSession.objects(user_id=user_id).all():
            if getattr(row, "revoked_at", None) is None:
                AuthSession.objects(
                    user_id=user_id, session_id=row.session_id
                ).update(revoked_at=now)
