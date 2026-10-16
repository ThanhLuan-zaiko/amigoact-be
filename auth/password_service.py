"""Password lifecycle mixin: reset codes, changes, dev challenges."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from core.exceptions import (
    ExpiredCodeError,
    InvalidCodeError,
    InvalidCredentialsError,
    NotFoundError,
    SamePasswordError,
)
from core.security import expired, hash_token, new_numeric_code, utcnow


class PasswordLifecycleMixin:
    """Split the password flows out of AuthService for file size."""

    def forgot_password(self, email: str, ip: str) -> None:
        """Issue a reset code. Always silent about account existence."""
        self._check_rate(
            f"code:{ip}",
            self._settings.code_max_attempts,
            self._settings.code_window_seconds,
        )
        user = self._users.get_by_email(email)
        if user is None:
            return
        code = new_numeric_code()
        self._resets.issue(
            code_hash=hash_token(code),
            user_id=user.id,
            expires_at=utcnow()
            + timedelta(minutes=self._settings.reset_code_ttl_minutes),
        )
        self._mailer.send_code(email, "AmigoACT password reset code", code)

    def reset_password(self, email: str, code: str, new_password: str) -> None:
        """Consume a reset code, set the password, burn all sessions."""
        user = self._users.get_by_email(email)
        row = self._resets.get_by_hash(hash_token(code))
        if user is None or row is None or row.user_id != user.id:
            raise InvalidCodeError("Reset code is invalid.")
        if row.used_at is not None:
            raise InvalidCodeError("Reset code is invalid.")
        if expired(row.expires_at):
            raise ExpiredCodeError("Reset code has expired.")
        now = utcnow()
        self._resets.mark_used(row.token_hash, now)
        self._users.set_password_hash(user.id, self._hasher.hash(new_password), now)
        self._refresh_tokens.revoke_all_for_user(user.id, now)
        if self._sessions is not None:
            self._sessions.revoke_all(user.id, now)

    def change_password(
        self, user_id: UUID, current_password: str, new_password: str,
        current_token_hash: str | None,
    ) -> None:
        """Rotate the password after proving the current one survives."""
        user = self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found.")
        if not self._hasher.verify(user.password_hash, current_password):
            raise InvalidCredentialsError("Current password is incorrect.")
        if self._hasher.verify(user.password_hash, new_password):
            raise SamePasswordError(
                "New password must differ from the current password."
            )
        now = utcnow()
        self._users.set_password_hash(user.id, self._hasher.hash(new_password), now)
        self._refresh_tokens.revoke_all_for_user(
            user.id, now, except_hash=current_token_hash
        )
        if self._sessions is None:
            return
        keep = (
            self._refresh_tokens.get_by_hash(current_token_hash).family_id
            if current_token_hash
            else None
        )
        for session in self._sessions.list_mine(user.id):
            if session.session_id != keep:
                self._sessions.revoke(user.id, session.session_id, now)

    def dev_challenge_code(self, email: str, kind: str) -> tuple[str, int]:
        """Dev-only plaintext code issuance (router guards ENV=dev)."""
        user = self._users.get_by_email(email)
        if user is None:
            raise NotFoundError("User not found.")
        code = new_numeric_code()
        if kind == "reset":
            ttl = self._settings.reset_code_ttl_minutes
            self._resets.issue(
                hash_token(code), user.id, utcnow() + timedelta(minutes=ttl)
            )
        else:
            ttl = self._settings.verification_code_ttl_minutes
            self._verifications.issue(
                hash_token(code), user.id, email, utcnow() + timedelta(minutes=ttl)
            )
        return code, ttl * 60
