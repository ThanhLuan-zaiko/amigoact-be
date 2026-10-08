"""Argon2id password hashing. Single wrapper module (AGENTS.md section 7)."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_DEFAULT_PARAMS: dict[str, int] = {
    "time_cost": 3,
    "memory_cost": 65536,
    "parallelism": 4,
    "hash_len": 32,
    "salt_len": 16,
}

_TEST_PARAMS: dict[str, int] = {
    "time_cost": 1,
    "memory_cost": 8192,
    "parallelism": 1,
    "hash_len": 32,
    "salt_len": 16,
}

_default_hasher = PasswordHasher(**_DEFAULT_PARAMS)


def build_hasher(for_tests: bool = False) -> PasswordHasher:
    """Create a hasher with production (default) or fast test parameters."""
    return PasswordHasher(**(_TEST_PARAMS if for_tests else _DEFAULT_PARAMS))


def hash_password(plain: str, hasher: PasswordHasher | None = None) -> str:
    """Hash a plaintext password. Never store or log the input."""
    return (hasher or _default_hasher).hash(plain)


def verify_password(stored_hash: str, candidate: str) -> bool:
    """Return True when the candidate matches. Generic failure, no reason."""
    try:
        _default_hasher.verify(stored_hash, candidate)
        return True
    except VerifyMismatchError:
        return False


def needs_rehash(stored_hash: str) -> bool:
    """Report whether a stored hash should be regenerated with current params."""
    return _default_hasher.check_needs_rehash(stored_hash)
