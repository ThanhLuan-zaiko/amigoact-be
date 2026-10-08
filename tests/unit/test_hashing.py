"""Unit tests for the Argon2id wrapper (fast test parameters)."""

from argon2.exceptions import VerifyMismatchError

from core.hashing import build_hasher, hash_password, needs_rehash


def test_hash_produces_argon2id_digest() -> None:
    hasher = build_hasher(for_tests=True)
    stored = hash_password("Aa1!secure", hasher)
    assert stored != "Aa1!secure"
    assert stored.startswith("$argon2id$")


def test_test_hasher_verifies_correct_password() -> None:
    hasher = build_hasher(for_tests=True)
    stored = hash_password("Aa1!secure", hasher)
    assert hasher.verify(stored, "Aa1!secure") is True


def test_test_hasher_rejects_wrong_password() -> None:
    hasher = build_hasher(for_tests=True)
    stored = hash_password("Aa1!secure", hasher)
    try:
        hasher.verify(stored, "Wrong1!xx")
        accepted = True
    except VerifyMismatchError:
        accepted = False
    assert accepted is False


def test_production_params_flag_test_hash_for_rehash() -> None:
    stored = hash_password("Aa1!secure", build_hasher(for_tests=True))
    assert needs_rehash(stored) is True


def test_production_hash_needs_no_rehash() -> None:
    stored = hash_password("Aa1!secure")
    assert needs_rehash(stored) is False
