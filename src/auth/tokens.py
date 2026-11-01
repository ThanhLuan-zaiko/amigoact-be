"""JWT access tokens and opaque single-purpose tokens."""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

JWT_ALGORITHM = "HS256"
JWT_ISSUER = "amigoact"
ACCESS_TOKEN_TYPE = "access"


class InvalidAccessTokenError(Exception):
    """The access token is malformed, expired, or not signed by this server."""


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID


def create_access_token(
    user_id: uuid.UUID, session_id: uuid.UUID, secret: str, ttl: timedelta
) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": JWT_ISSUER,
        "sub": str(user_id),
        "sid": str(session_id),
        "typ": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(claims, secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, secret: str) -> AccessClaims:
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            options={"require": ["exp", "iat", "iss", "sub", "sid", "typ"]},
        )
        if claims["typ"] != ACCESS_TOKEN_TYPE:
            raise InvalidAccessTokenError
        return AccessClaims(uuid.UUID(claims["sub"]), uuid.UUID(claims["sid"]))
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise InvalidAccessTokenError from exc


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def hash_opaque_token(token: str) -> str:
    """Only this SHA-256 hash is stored, so a database leak exposes no usable token."""
    return hashlib.sha256(token.encode()).hexdigest()
