"""Shared in-memory ports for AuthService unit tests (no I/O)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from auth.interfaces import (
    PasswordHasherPort,
    PasswordResetStore,
    RateLimiter,
    RefreshTokenStore,
    SessionStore,
    UserRepository,
    VerificationCodeStore,
)
from auth.service import AuthService
from core.config import Settings
from core.email import EmailSender
from core.hashing import build_hasher
from tests.unit.org_fakes import FakeMedia

EMAIL = "student@example.com"
PHONE = "0912345678"
PASSWORD = "Aa1!secure"
NAME = "Nguyen Van A"


class FakeUsers(UserRepository):
    def __init__(self) -> None:
        self.by_id: dict[UUID, Any] = {}
        self.by_email: dict[str, Any] = {}
        self.by_phone: dict[str, Any] = {}

    def create(self, user_id, email, phone, password_hash, full_name, now, account_type="individual", tax_code=None, company_name=None, legal_rep_name=None, legal_rep_id=None, legal_rep_position=None):  # noqa: ANN001, ANN202
        user = SimpleNamespace(
            id=user_id, email=email, phone=phone, password_hash=password_hash,
            full_name=full_name, account_type=account_type, tax_code=tax_code,
            company_name=company_name, legal_rep_name=legal_rep_name,
            legal_rep_id=legal_rep_id, legal_rep_position=legal_rep_position,
            date_of_birth=None, gender=None, address=None,
            avatar_media_id=None, last_login_at=None,
            email_verified_at=None, status="active",
            created_at=now, updated_at=now,
        )
        self.by_id[user_id] = user
        self.by_email[email] = user
        self.by_phone[phone] = user
        return user

    def get_by_id(self, user_id):  # noqa: ANN001, ANN202
        return self.by_id.get(user_id)

    def update_profile(self, user_id, full_name, date_of_birth, gender, address, now):  # noqa: ANN001, ANN202
        user = self.by_id.get(user_id)
        if user is None:
            return None
        user.full_name = full_name
        user.date_of_birth = date_of_birth
        user.gender = gender
        user.address = address
        user.updated_at = now
        return user

    def mark_login(self, user_id, now):  # noqa: ANN001, ANN202
        user = self.by_id.get(user_id)
        if user is not None:
            user.last_login_at = now

    def set_avatar_media(self, user_id, asset_id, now):  # noqa: ANN001, ANN202
        user = self.by_id.get(user_id)
        if user is not None:
            user.avatar_media_id = asset_id
            user.updated_at = now

    def get_by_email(self, email):  # noqa: ANN001, ANN202
        return self.by_email.get(email)

    def get_by_phone(self, phone):  # noqa: ANN001, ANN202
        return self.by_phone.get(phone)

    def mark_email_verified(self, user_id, now):  # noqa: ANN001, ANN202
        user = self.by_id[user_id]
        user.email_verified_at = now
        user.updated_at = now

    def set_password_hash(self, user_id, password_hash, now):  # noqa: ANN001, ANN202
        user = self.by_id[user_id]
        user.password_hash = password_hash
        user.updated_at = now


class FakeRefresh(RefreshTokenStore):
    def __init__(self) -> None:
        self.rows: dict[str, Any] = {}

    def create(self, token_hash, user_id, family_id, expires_at, rotated_from, now):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            token_hash=token_hash, user_id=user_id, family_id=family_id,
            expires_at=expires_at, revoked_at=None, rotated_from=rotated_from,
            created_at=now,
        )
        self.rows[token_hash] = row
        return row

    def get_by_hash(self, token_hash):  # noqa: ANN001, ANN202
        return self.rows.get(token_hash)

    def revoke_one(self, token_hash, now):  # noqa: ANN001, ANN202
        if token_hash in self.rows:
            self.rows[token_hash].revoked_at = now

    def revoke_family(self, family_id, now, except_hash=None):  # noqa: ANN001, ANN202
        for row in self.rows.values():
            if row.family_id == family_id and row.token_hash != except_hash:
                row.revoked_at = now

    def revoke_all_for_user(self, user_id, now, except_hash=None):  # noqa: ANN001, ANN202
        for row in self.rows.values():
            if row.user_id == user_id and row.token_hash != except_hash:
                row.revoked_at = now


class FakeSessions(SessionStore):
    def __init__(self) -> None:
        self.rows: dict[UUID, Any] = {}

    def create(self, user_id, session_id, device_label, user_agent, ip, expires_at, now):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            user_id=user_id, session_id=session_id, device_label=device_label,
            user_agent=user_agent, ip=ip, created_at=now, last_seen_at=now,
            expires_at=expires_at, revoked_at=None,
        )
        self.rows[session_id] = row
        return row

    def touch(self, user_id, session_id, now):  # noqa: ANN001, ANN202
        if session_id in self.rows:
            self.rows[session_id].last_seen_at = now

    def list_mine(self, user_id):  # noqa: ANN001, ANN202
        return [r for r in self.rows.values() if r.user_id == user_id]

    def get(self, user_id, session_id):  # noqa: ANN001, ANN202
        row = self.rows.get(session_id)
        return row if row is not None and row.user_id == user_id else None

    def revoke(self, user_id, session_id, now):  # noqa: ANN001, ANN202
        row = self.get(user_id, session_id)
        if row is not None:
            row.revoked_at = now

    def revoke_all(self, user_id, now):  # noqa: ANN001, ANN202
        for row in self.list_mine(user_id):
            row.revoked_at = now


class FakeCodes(VerificationCodeStore, PasswordResetStore):
    def __init__(self) -> None:
        self.rows: dict[str, Any] = {}

    def issue(self, code_hash, user_id, *extra, expires_at=None, email=None):  # noqa: ANN001, ANN002, ANN202
        row = SimpleNamespace(
            token_hash=code_hash, user_id=user_id,
            email=email if email is not None else next(iter(extra), ""),
            expires_at=expires_at if expires_at is not None else extra[-1],
            verified_at=None, used_at=None,
        )
        self.rows[code_hash] = row
        return row

    def get_by_hash(self, code_hash):  # noqa: ANN001, ANN202
        return self.rows.get(code_hash)

    def mark_used(self, code_hash, now):  # noqa: ANN001, ANN202
        self.rows[code_hash].verified_at = now
        self.rows[code_hash].used_at = now


class FakeLimiter(RateLimiter):
    def __init__(self) -> None:
        self.hits: dict[str, int] = {}

    def hit(self, bucket: str, window_seconds: int) -> int:
        del window_seconds
        self.hits[bucket] = self.hits.get(bucket, 0) + 1
        return self.hits[bucket]


class StubHasher(PasswordHasherPort):
    def __init__(self) -> None:
        self._hasher = build_hasher(for_tests=True)

    def hash(self, plain: str) -> str:
        return self._hasher.hash(plain)

    def verify(self, stored_hash: str, candidate: str) -> bool:
        try:
            self._hasher.verify(stored_hash, candidate)
            return True
        except Exception:
            return False

    def needs_rehash(self, stored_hash: str) -> bool:
        return True


class FakeMailer(EmailSender):
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send_code(self, to_email: str, subject: str, code: str) -> bool:
        self.sent.append((to_email, subject, code))
        return True


def make_service(**overrides: Any) -> tuple[AuthService, dict[str, Any]]:
    parts: dict[str, Any] = {
        "users": FakeUsers(),
        "refresh_tokens": FakeRefresh(),
        "verifications": FakeCodes(),
        "resets": FakeCodes(),
        "limiter": FakeLimiter(),
        "hasher": StubHasher(),
        "mailer": FakeMailer(),
        "settings": Settings(jwt_secret="unit-test-secret-32-bytes-long!!"),
        "media": FakeMedia(),
        "sessions": FakeSessions(),
    }
    parts.update(overrides)
    return AuthService(**parts), parts  # type: ignore[arg-type]


def verified_pair(service: AuthService, parts: dict[str, Any]) -> Any:
    service.register(EMAIL, PHONE, PASSWORD, NAME)
    user = parts["users"].get_by_email(EMAIL)
    service._users.mark_email_verified(user.id, user.created_at)
    return service.login(EMAIL, PASSWORD, "127.0.0.1")
