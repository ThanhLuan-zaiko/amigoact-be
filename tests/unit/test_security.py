"""Unit tests for JWT and opaque-token helpers (no I/O)."""

import re

import jwt
import pytest

from core.security import (
    AuthTokenError,
    create_access_token,
    decode_access_token,
    hash_token,
    new_numeric_code,
    new_opaque_token,
    verify_token,
)

SECRET = "unit-test-secret-at-least-32-bytes!"


def test_access_token_roundtrip_claims() -> None:
    token = create_access_token("user-1", SECRET, ttl_seconds=600)
    payload = decode_access_token(token, SECRET)
    assert payload["sub"] == "user-1"
    assert payload["type"] == "access"
    assert "jti" in payload and "iat" in payload and "exp" in payload


def test_expired_token_rejected() -> None:
    token = create_access_token("user-1", SECRET, ttl_seconds=-1)
    with pytest.raises(AuthTokenError):
        decode_access_token(token, SECRET)


def test_wrong_type_rejected() -> None:
    from core.security import utcnow

    forged = jwt.encode(
        {"sub": "user-1", "type": "refresh", "exp": 9999999999,
         "iat": int(utcnow().timestamp())},
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(AuthTokenError):
        decode_access_token(forged, SECRET)


def test_tampered_signature_rejected() -> None:
    token = create_access_token("user-1", SECRET)
    with pytest.raises(AuthTokenError):
        decode_access_token(token + "x", SECRET)


def test_opaque_token_hash_verifies_timing_safe() -> None:
    token = new_opaque_token()
    assert verify_token(token, hash_token(token)) is True
    assert verify_token(token + "x", hash_token(token)) is False
    assert hash_token(token) != token


def test_numeric_code_is_zero_padded_six_digits() -> None:
    for _ in range(50):
        assert re.fullmatch(r"\d{6}", new_numeric_code())
