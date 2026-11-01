"""Password hashing with Argon2id."""

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type

# argon2-cffi defaults follow the RFC 9106 low-memory profile.
_hasher = PasswordHasher(type=Type.ID)
# Verified when an account has no hash, so unknown emails take as long as known ones.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        verified = _hasher.verify(password_hash or _DUMMY_HASH, password)
    except VerificationError, InvalidHashError:
        return False
    return verified and password_hash is not None


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
