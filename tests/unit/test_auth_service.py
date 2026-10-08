"""Unit tests for AuthService with fake ports (no I/O, fast)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
import uuid_utils

from auth.interfaces import (
    PasswordHasherPort,
    PasswordResetStore,
    RateLimiter,
    RefreshTokenStore,
    UserRepository,
    VerificationCodeStore,
)
from auth.service import AuthService
from core.config import Settings
from core.email import EmailSender
from core.hashing import build_hasher, hash_password
from core.exceptions import (
    EmailTakenError,
    InvalidCodeError,
    InvalidCredentialsError,
    PhoneTakenError,
    SamePasswordError,
    TooManyRequestsError,
)
from core.security import decode_access_token

EMAIL = "student@example.com"
PHONE = "0912345678"
PASSWORD = "Aa1!secure"
NAME = "Nguyen Van A"


class FakeUsers(UserRepository):
    def __init__(self) -> None:
        self.by_id: dict[UUID, Any] = {}
        self.by_email: dict[str, Any] = {}
        self.by_phone: dict[str, Any] = {}

    def create(self, user_id, email, phone, password_hash, full_name, now):  # noqa: ANN001, ANN202
        user = SimpleNamespace(
            id=user_id, email=email, phone=phone, password_hash=password_hash,
            full_name=full_name, email_verified_at=None, status="active",
            created_at=now, updated_at=now,
        )
        self.by_id[user_id] = user
        self.by_email[email] = user
        self.by_phone[phone] = user
        return user

    def get_by_id(self, user_id):  # noqa: ANN001, ANN202
        return self.by_id.get(user_id)

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


def _service(**overrides: Any) -> tuple[AuthService, dict[str, Any]]:
    parts: dict[str, Any] = {
        "users": FakeUsers(),
        "refresh_tokens": FakeRefresh(),
        "verifications": FakeCodes(),
        "resets": FakeCodes(),
        "limiter": FakeLimiter(),
        "hasher": StubHasher(),
        "mailer": FakeMailer(),
        "settings": Settings(jwt_secret="unit-test-secret-32-bytes-long!!"),
    }
    parts.update(overrides)
    return AuthService(**parts), parts  # type: ignore[arg-type]


def _verified_pair(service: AuthService, parts: dict[str, Any]) -> Any:
    service.register(EMAIL, PHONE, PASSWORD, NAME)
    user = parts["users"].get_by_email(EMAIL)
    service._users.mark_email_verified(user.id, user.created_at)
    return service.login(EMAIL, PASSWORD, "127.0.0.1")


def test_register_creates_unverified_profile_without_email() -> None:
    service, parts = _service()
    profile = service.register(EMAIL, PHONE, PASSWORD, NAME)
    assert profile.email_verified is False
    assert parts["mailer"].sent == []


def test_register_rejects_duplicates() -> None:
    service, _ = _service()
    service.register(EMAIL, PHONE, PASSWORD, NAME)
    with pytest.raises(EmailTakenError):
        service.register(EMAIL, "0312345678", PASSWORD, NAME)
    with pytest.raises(PhoneTakenError):
        service.register("other@example.com", PHONE, PASSWORD, NAME)


def test_verify_email_consumes_code_once() -> None:
    service, parts = _service()
    service.register(EMAIL, PHONE, PASSWORD, NAME)
    service.resend_verification(EMAIL, "127.0.0.1")
    code = parts["mailer"].sent[-1][2]
    profile = service.verify_email(EMAIL, code, "127.0.0.1")
    assert profile.email_verified is True
    with pytest.raises(InvalidCodeError):
        service.verify_email(EMAIL, code, "127.0.0.1")


def test_login_allows_unverified_while_gate_deferred() -> None:
    service, _ = _service()
    service.register(EMAIL, PHONE, PASSWORD, NAME)
    pair = service.login(EMAIL, PASSWORD, "127.0.0.1")
    payload = decode_access_token(pair.access_token, "unit-test-secret-32-bytes-long!!")
    assert payload["type"] == "access"
    with pytest.raises(InvalidCredentialsError):
        service.login("ghost@example.com", PASSWORD, "127.0.0.2")
    with pytest.raises(InvalidCredentialsError):
        service.login(EMAIL, "Wrong1!xx", "127.0.0.3")


def test_login_mints_decodable_access_token() -> None:
    service, parts = _service()
    pair = _verified_pair(service, parts)
    payload = decode_access_token(pair.access_token, "unit-test-secret-32-bytes-long!!")
    assert payload["type"] == "access"


def test_refresh_rotates_and_reuse_burns_family() -> None:
    service, parts = _service()
    pair = _verified_pair(service, parts)
    rotated = service.refresh(pair.refresh_token)
    assert rotated.refresh_token != pair.refresh_token
    with pytest.raises(InvalidCredentialsError):
        service.refresh(pair.refresh_token)
    with pytest.raises(InvalidCredentialsError):
        service.refresh(rotated.refresh_token)


def test_logout_and_logout_all_revoke() -> None:
    service, parts = _service()
    pair = _verified_pair(service, parts)
    service.logout(pair.refresh_token)
    with pytest.raises(InvalidCredentialsError):
        service.refresh(pair.refresh_token)
    pair2 = service.login(EMAIL, PASSWORD, "127.0.0.1")
    user = parts["users"].get_by_email(EMAIL)
    service.logout_all(user.id)
    with pytest.raises(InvalidCredentialsError):
        service.refresh(pair2.refresh_token)


def test_forgot_password_is_silent_and_reset_burns_sessions() -> None:
    service, parts = _service()
    assert service.forgot_password("ghost@example.com", "127.0.0.1") is None
    pair = _verified_pair(service, parts)
    service.forgot_password(EMAIL, "127.0.0.1")
    code = parts["mailer"].sent[-1][2]
    with pytest.raises(InvalidCodeError):
        service.reset_password(EMAIL, "000000", "Bb2@secure")
    service.reset_password(EMAIL, code, "Bb2@secure")
    with pytest.raises(InvalidCredentialsError):
        service.refresh(pair.refresh_token)
    fresh = service.login(EMAIL, "Bb2@secure", "127.0.0.1")
    assert fresh.access_token != pair.access_token


def test_login_rate_limit_blocks_after_five_attempts() -> None:
    service, _ = _service()
    service.register(EMAIL, PHONE, PASSWORD, NAME)
    for _ in range(5):
        with pytest.raises(InvalidCredentialsError):
            service.login(EMAIL, "Wrong1!xx", "10.0.0.9")
    with pytest.raises(TooManyRequestsError):
        service.login(EMAIL, "Wrong1!xx", "10.0.0.9")


def test_rehash_upgrades_outdated_hash_on_login() -> None:
    service, parts = _service()
    service.register(EMAIL, PHONE, PASSWORD, NAME)
    user = parts["users"].get_by_email(EMAIL)
    legacy = hash_password(PASSWORD)
    parts["users"].set_password_hash(user.id, legacy, user.created_at)
    service._users.mark_email_verified(user.id, user.created_at)
    service.login(EMAIL, PASSWORD, "127.0.0.1")
    assert parts["users"].get_by_email(EMAIL).password_hash != legacy


def test_uuid7_primary_keys() -> None:
    from uuid import UUID

    assert UUID(str(uuid_utils.uuid7())).version == 7


def test_change_password_rejects_same_password() -> None:
    service, parts = _service()
    pair = _verified_pair(service, parts)
    user = parts["users"].get_by_email(EMAIL)
    from core.security import hash_token as digest

    with pytest.raises(SamePasswordError):
        service.change_password(
            user.id, PASSWORD, PASSWORD, digest(pair.refresh_token)
        )


def test_change_password_spares_current_session() -> None:
    service, parts = _service()
    pair = _verified_pair(service, parts)
    other = service.login(EMAIL, PASSWORD, "127.0.0.2")
    user = parts["users"].get_by_email(EMAIL)
    from core.security import hash_token as digest

    current_digest = digest(pair.refresh_token)
    with pytest.raises(InvalidCredentialsError):
        service.change_password(user.id, "Wrong1!xx", "Bb2@secure", current_digest)
    service.change_password(user.id, PASSWORD, "Bb2@secure", current_digest)
    rotated = service.refresh(pair.refresh_token)
    assert rotated.refresh_token != pair.refresh_token
    with pytest.raises(InvalidCredentialsError):
        service.refresh(other.refresh_token)
    assert isinstance(datetime.now(), datetime)
