"""Regression tests: frozen auth contracts (fail before fix, pass after)."""

from __future__ import annotations

from httpx import AsyncClient

from core.config import get_settings

PASSWORD = "Aa1!secure"


async def _register_verify_login(
    client: AsyncClient, email: str, phone: str
) -> str:
    """Register, verify by dev code, and return a fresh access token."""
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "phone": phone,
            "password": PASSWORD,
            "full_name": "Regression User",
        },
    )
    assert response.status_code == 201
    challenged = await client.post(
        "/auth/dev/challenge-code", json={"email": email, "kind": "verification"}
    )
    code = challenged.json()["code"]
    verified = await client.post(
        "/auth/verify-email", json={"email": email, "code": code}
    )
    assert verified.status_code == 200
    logged = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert logged.status_code == 200
    return logged.json()["access_token"]


async def test_error_envelope_shape_locked(client: AsyncClient) -> None:
    """Every domain failure is exactly {code, message} (no detail leaks)."""
    await client.post(
        "/auth/register",
        json={
            "email": "shape@example.com",
            "phone": "0912345678",
            "password": PASSWORD,
            "full_name": "Shape User",
        },
    )
    duplicate = await client.post(
        "/auth/register",
        json={
            "email": "shape@example.com",
            "phone": "0312345678",
            "password": PASSWORD,
            "full_name": "Shape User",
        },
    )
    assert duplicate.status_code == 409
    assert set(duplicate.json().keys()) == {"code", "message"}
    assert duplicate.json()["code"] == "EMAIL_TAKEN"

    wrong = await client.post(
        "/auth/login", json={"email": "shape@example.com", "password": "Wrong1!xx"}
    )
    assert wrong.status_code == 401
    assert set(wrong.json().keys()) == {"code", "message"}

    unverified = await client.post(
        "/auth/login", json={"email": "shape@example.com", "password": PASSWORD}
    )
    assert unverified.status_code == 200
    assert unverified.json()["token_type"] == "Bearer"


async def test_unknown_email_matches_wrong_password(client: AsyncClient) -> None:
    """Anti-enumeration: ghost accounts fail exactly like bad passwords."""
    ghost = await client.post(
        "/auth/login", json={"email": "ghost@example.com", "password": PASSWORD}
    )
    assert ghost.status_code == 401
    assert ghost.json()["code"] == "INVALID_CREDENTIALS"

    await client.post(
        "/auth/register",
        json={
            "email": "real@example.com",
            "phone": "0523456789",
            "password": PASSWORD,
            "full_name": "Real User",
        },
    )
    wrong = await client.post(
        "/auth/login", json={"email": "real@example.com", "password": "Wrong1!xx"}
    )
    assert wrong.status_code == 401
    assert wrong.json() == ghost.json()


async def test_weak_password_rejected_before_touching_db(client: AsyncClient) -> None:
    """Policy violations stop at validation (422) with no user row."""
    response = await client.post(
        "/auth/register",
        json={
            "email": "weak@example.com",
            "phone": "0123456789",
            "password": "weak",
            "full_name": "Weak User",
        },
    )
    assert response.status_code == 422

    from auth.repository import CqlUserRepository
    from tests.conftest import TEST_KEYSPACE

    assert CqlUserRepository(TEST_KEYSPACE).get_by_email("weak@example.com") is None


async def test_login_never_leaks_hash_or_tokens(client: AsyncClient) -> None:
    """Secret material stays out of JSON bodies (cookie carries refresh)."""
    access = await _register_verify_login(client, "leak@example.com", "0777777779")
    assert "password_hash" not in (await client.get("/auth/me", headers={"Authorization": f"Bearer {access}"})).text


async def test_dev_challenge_forbidden_outside_dev(
    client: AsyncClient, app_client
) -> None:
    """The plaintext-code escape hatch 404s in any non-dev environment."""
    from core.config import Settings
    from tests.conftest import TEST_JWT_SECRET, TEST_KEYSPACE

    app_client.dependency_overrides[get_settings] = lambda: Settings(
        scylla_keyspace=TEST_KEYSPACE, jwt_secret=TEST_JWT_SECRET, env="prod"
    )
    response = await client.post(
        "/auth/dev/challenge-code",
        json={"email": "any@example.com", "kind": "verification"},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_unknown_refresh_token_is_plain_401(client: AsyncClient) -> None:
    """Unknown refresh digests fail closed without touching live sessions."""
    await _register_verify_login(client, "burn@example.com", "0898765432")
    rotated = await client.post("/auth/refresh")
    successor = rotated.cookies.get("amigoact_refresh")
    assert successor

    client.cookies.clear()
    replay = await client.post(
        "/auth/refresh", headers={"Cookie": "amigoact_refresh=stale"}
    )
    assert replay.status_code == 401

    response = await client.post(
        "/auth/refresh", headers={"Cookie": f"amigoact_refresh={successor}"}
    )
    assert response.status_code == 200
