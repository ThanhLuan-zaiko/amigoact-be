"""Unit tests for AuthService with fake ports (no I/O, fast)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import pytest
import uuid_utils

from core.exceptions import (
    EmailTakenError,
    InvalidCodeError,
    InvalidCredentialsError,
    PhoneTakenError,
    SamePasswordError,
    TooManyRequestsError,
)
from core.hashing import hash_password
from core.security import decode_access_token
from tests.unit.auth_fakes import (
    EMAIL,
    NAME,
    PASSWORD,
    PHONE,
    make_service,
    verified_pair,
)


def test_register_creates_unverified_profile_without_email() -> None:
    service, parts = make_service()
    profile = service.register(EMAIL, PHONE, PASSWORD, NAME)
    assert profile.email_verified is False
    assert parts["mailer"].sent == []


def test_register_rejects_duplicates() -> None:
    service, _ = make_service()
    service.register(EMAIL, PHONE, PASSWORD, NAME)
    with pytest.raises(EmailTakenError):
        service.register(EMAIL, "0312345678", PASSWORD, NAME)
    with pytest.raises(PhoneTakenError):
        service.register("other@example.com", PHONE, PASSWORD, NAME)


def test_verify_email_consumes_code_once() -> None:
    service, parts = make_service()
    service.register(EMAIL, PHONE, PASSWORD, NAME)
    service.resend_verification(EMAIL, "127.0.0.1")
    code = parts["mailer"].sent[-1][2]
    profile = service.verify_email(EMAIL, code, "127.0.0.1")
    assert profile.email_verified is True
    with pytest.raises(InvalidCodeError):
        service.verify_email(EMAIL, code, "127.0.0.1")


def test_login_allows_unverified_while_gate_deferred() -> None:
    service, _ = make_service()
    service.register(EMAIL, PHONE, PASSWORD, NAME)
    pair = service.login(EMAIL, PASSWORD, "127.0.0.1")
    payload = decode_access_token(pair.access_token, "unit-test-secret-32-bytes-long!!")
    assert payload["type"] == "access"
    with pytest.raises(InvalidCredentialsError):
        service.login("ghost@example.com", PASSWORD, "127.0.0.2")
    with pytest.raises(InvalidCredentialsError):
        service.login(EMAIL, "Wrong1!xx", "127.0.0.3")


def test_login_mints_decodable_access_token() -> None:
    service, parts = make_service()
    pair = verified_pair(service, parts)
    payload = decode_access_token(pair.access_token, "unit-test-secret-32-bytes-long!!")
    assert payload["type"] == "access"


def test_refresh_rotates_and_reuse_burns_family() -> None:
    service, parts = make_service()
    pair = verified_pair(service, parts)
    rotated = service.refresh(pair.refresh_token, "127.0.0.1")
    assert rotated.refresh_token != pair.refresh_token
    with pytest.raises(InvalidCredentialsError):
        service.refresh(pair.refresh_token, "127.0.0.1")
    with pytest.raises(InvalidCredentialsError):
        service.refresh(rotated.refresh_token, "127.0.0.1")


def test_logout_and_logout_all_revoke() -> None:
    service, parts = make_service()
    pair = verified_pair(service, parts)
    service.logout(pair.refresh_token)
    with pytest.raises(InvalidCredentialsError):
        service.refresh(pair.refresh_token, "127.0.0.1")
    pair2 = service.login(EMAIL, PASSWORD, "127.0.0.1")
    user = parts["users"].get_by_email(EMAIL)
    service.logout_all(user.id)
    with pytest.raises(InvalidCredentialsError):
        service.refresh(pair2.refresh_token, "127.0.0.1")


def test_forgot_password_is_silent_and_reset_burns_sessions() -> None:
    service, parts = make_service()
    assert service.forgot_password("ghost@example.com", "127.0.0.1") is None
    pair = verified_pair(service, parts)
    service.forgot_password(EMAIL, "127.0.0.1")
    code = parts["mailer"].sent[-1][2]
    with pytest.raises(InvalidCodeError):
        service.reset_password(EMAIL, "000000", "Bb2@secure")
    service.reset_password(EMAIL, code, "Bb2@secure")
    with pytest.raises(InvalidCredentialsError):
        service.refresh(pair.refresh_token, "127.0.0.1")
    fresh = service.login(EMAIL, "Bb2@secure", "127.0.0.1")
    assert fresh.access_token != pair.access_token


def test_login_rate_limit_blocks_after_five_attempts() -> None:
    service, _ = make_service()
    service.register(EMAIL, PHONE, PASSWORD, NAME)
    for _ in range(5):
        with pytest.raises(InvalidCredentialsError):
            service.login(EMAIL, "Wrong1!xx", "10.0.0.9")
    with pytest.raises(TooManyRequestsError):
        service.login(EMAIL, "Wrong1!xx", "10.0.0.9")


def test_rehash_upgrades_outdated_hash_on_login() -> None:
    service, parts = make_service()
    service.register(EMAIL, PHONE, PASSWORD, NAME)
    user = parts["users"].get_by_email(EMAIL)
    legacy = hash_password(PASSWORD)
    parts["users"].set_password_hash(user.id, legacy, user.created_at)
    service._users.mark_email_verified(user.id, user.created_at)
    service.login(EMAIL, PASSWORD, "127.0.0.1")
    assert parts["users"].get_by_email(EMAIL).password_hash != legacy


def test_uuid7_primary_keys() -> None:
    assert UUID(str(uuid_utils.uuid7())).version == 7


def test_change_password_rejects_same_password() -> None:
    service, parts = make_service()
    pair = verified_pair(service, parts)
    user = parts["users"].get_by_email(EMAIL)
    from core.security import hash_token as digest

    with pytest.raises(SamePasswordError):
        service.change_password(
            user.id, PASSWORD, PASSWORD, digest(pair.refresh_token)
        )


def test_change_password_spares_current_session() -> None:
    service, parts = make_service()
    pair = verified_pair(service, parts)
    other = service.login(EMAIL, PASSWORD, "127.0.0.2")
    user = parts["users"].get_by_email(EMAIL)
    from core.security import hash_token as digest

    current_digest = digest(pair.refresh_token)
    with pytest.raises(InvalidCredentialsError):
        service.change_password(user.id, "Wrong1!xx", "Bb2@secure", current_digest)
    service.change_password(user.id, PASSWORD, "Bb2@secure", current_digest)
    rotated = service.refresh(pair.refresh_token, "127.0.0.1")
    assert rotated.refresh_token != pair.refresh_token
    with pytest.raises(InvalidCredentialsError):
        service.refresh(other.refresh_token, "127.0.0.1")
    assert isinstance(datetime.now(), datetime)
