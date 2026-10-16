"""Session management: list devices, revoke sessions by family id."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from auth.interfaces import RefreshTokenStore, SessionStore
from core.exceptions import NotFoundError
from core.security import utcnow


@dataclass(frozen=True)
class SessionView:
    """Public session shape; never carries token material."""

    session_id: UUID
    device_label: str | None
    user_agent: str | None
    ip: str | None
    created_at: datetime | None
    last_seen_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    current: bool


def _view(row, current_family: UUID | None) -> SessionView:
    return SessionView(
        session_id=row.session_id,
        device_label=row.device_label,
        user_agent=row.user_agent,
        ip=row.ip,
        created_at=row.created_at,
        last_seen_at=row.last_seen_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        current=row.session_id == current_family,
    )


class SessionService:
    """Read and revoke the caller's login sessions."""

    def __init__(
        self,
        sessions: SessionStore,
        refresh_tokens: RefreshTokenStore,
    ) -> None:
        self._sessions = sessions
        self._refresh_tokens = refresh_tokens

    def list_mine(
        self, user_id: UUID, current_token_hash: str | None
    ) -> list[SessionView]:
        """Every session; newest first; flags the caller's own device."""
        family = None
        if current_token_hash:
            row = self._refresh_tokens.get_by_hash(current_token_hash)
            family = getattr(row, "family_id", None)
        rows = self._sessions.list_mine(user_id)
        rows.sort(key=lambda r: r.created_at or datetime.min, reverse=True)
        return [_view(row, family) for row in rows]

    def revoke(self, user_id: UUID, session_id: UUID) -> None:
        """Burn one session's whole token family plus the session row."""
        row = self._sessions.get(user_id, session_id)
        if row is None:
            raise NotFoundError("Session not found.")
        now = utcnow()
        self._sessions.revoke(user_id, session_id, now)
        self._refresh_tokens.revoke_family(session_id, now)
