import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import ValidationError

from src.auth.passwords import hash_password, verify_password
from src.auth.rate_limit import seconds_until_reset, window_start
from src.auth.schemas import ProfileUpdateRequest, RegisterRequest
from src.auth.tokens import (
    InvalidAccessTokenError,
    create_access_token,
    decode_access_token,
    hash_opaque_token,
    new_opaque_token,
)

SECRET = "unit-test-secret-that-is-long-enough-for-hs256"
BASE = {"email": "a@example.com", "password": "Long-enough-1", "full_name": "A"}


def test_password_hash_uses_argon2id_and_verifies() -> None:
    hashed = hash_password("long enough")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "long enough")
    assert not verify_password(hashed, "wrong password")


def test_verify_password_is_false_without_a_hash() -> None:
    assert not verify_password(None, "anything")


def test_access_token_round_trip() -> None:
    user_id, session_id = uuid.uuid7(), uuid.uuid7()
    token = create_access_token(user_id, session_id, SECRET, timedelta(minutes=5))
    claims = decode_access_token(token, SECRET)
    assert (claims.user_id, claims.session_id) == (user_id, session_id)


def test_expired_access_token_is_rejected() -> None:
    token = create_access_token(
        uuid.uuid7(), uuid.uuid7(), SECRET, timedelta(seconds=-1)
    )
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token, SECRET)


def test_access_token_with_other_secret_is_rejected() -> None:
    token = create_access_token(
        uuid.uuid7(), uuid.uuid7(), SECRET, timedelta(minutes=5)
    )
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token, SECRET + "x")


def test_token_with_wrong_type_is_rejected() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": "amigoact",
            "sub": str(uuid.uuid7()),
            "sid": str(uuid.uuid7()),
            "typ": "refresh",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token, SECRET)


def test_opaque_tokens_are_unique_and_hash_is_stable() -> None:
    first, second = new_opaque_token(), new_opaque_token()
    assert first != second
    assert hash_opaque_token(first) == hash_opaque_token(first)
    assert hash_opaque_token(first) != first


def test_rate_limit_window_helpers() -> None:
    now = datetime(2026, 1, 1, 10, 7, 30, tzinfo=UTC)
    assert window_start(now, 900) == datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    assert seconds_until_reset(now, 900) == 450


@pytest.mark.parametrize(
    "change",
    [
        {"password": "short"},
        {"password": "x" * 129},
        {"email": "not-an-email"},
        {"full_name": "   "},
        {"phone": "12-34"},
        {"account_type": "admin"},
        {"account_type": "business"},
    ],
)
def test_register_request_rejects_bad_input(change: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest.model_validate({**BASE, **change})


def test_register_request_accepts_complete_business_account() -> None:
    request = RegisterRequest.model_validate(
        {
            **BASE,
            "account_type": "business",
            "tax_code": "0101234567",
            "company_name": "Co",
        }
    )
    assert request.account_type == "business"


def test_profile_update_tracks_only_sent_fields() -> None:
    request = ProfileUpdateRequest.model_validate({"address": None})
    assert request.model_fields_set == {"address"}


@pytest.mark.parametrize(
    "body",
    [{"full_name": None}, {"date_of_birth": "2999-01-01"}, {"gender": "unknown"}],
)
def test_profile_update_rejects_bad_input(body: dict[str, str | None]) -> None:
    with pytest.raises(ValidationError):
        ProfileUpdateRequest.model_validate(body)
