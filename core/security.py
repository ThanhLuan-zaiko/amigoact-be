"""JWT access tokens plus opaque-token helpers (AGENTS.md section 8)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
import uuid_utils

ACCESS_TOKEN_TYPE = "access"
_TOKEN_BYTES = 32
_NUMERIC_CODE_DIGITS = 6


def utcnow() -> datetime:
    """Timezone-aware current UTC time for all token timestamps."""
    return datetime.now(timezone.utc)


def utc_aware(moment: datetime | None) -> datetime | None:
    """Reattach UTC to a naive DB datetime so clients see real instants."""
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def new_token_id() -> str:
    """Random UUIDv7 identifier for access-token jti claims."""
    return str(uuid_utils.uuid7())


def create_access_token(
    user_id: str,
    secret: str,
    ttl_seconds: int = 900,
    roles: tuple[str, ...] = (),
) -> str:
    """Issue a short-lived HS256 JWT with type, jti, iat and exp claims."""
    now = utcnow()
    payload = {
        "sub": user_id,
        "type": ACCESS_TOKEN_TYPE,
        "roles": list(roles),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        "jti": new_token_id(),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, secret: str) -> dict[str, object]:
    """Validate signature, expiry and type. Raises AuthTokenError on failure."""
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise AuthTokenError("Invalid access token.") from exc
    if payload.get("type") != ACCESS_TOKEN_TYPE or "sub" not in payload:
        raise AuthTokenError("Invalid access token.")
    return payload


class AuthTokenError(Exception):
    """Raised for expired, malformed or wrong-type access tokens."""


def new_opaque_token() -> str:
    """Generate a 256-bit random refresh token for cookie transport."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def new_numeric_code() -> str:
    """Generate a zero-padded 6-digit verification/reset code."""
    return f"{secrets.randbelow(10**_NUMERIC_CODE_DIGITS):06d}"


def hash_token(token: str) -> str:
    """SHA-256 hex digest. Only digests are persisted, never plaintext."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token(candidate: str, stored_hash: str) -> bool:
    """Timing-safe comparison of a candidate against a stored digest."""
    return hmac.compare_digest(hash_token(candidate), stored_hash)
