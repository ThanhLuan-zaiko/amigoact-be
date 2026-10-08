"""Integration tests: router to ScyllaDB over HTTP (amigoact_test)."""

from __future__ import annotations

from httpx import AsyncClient

PASSWORD = "Aa1!secure"
NEW_PASSWORD = "Bb2@secure"


def _payload(email: str, phone: str) -> dict[str, str]:
    return {
        "email": email,
        "phone": phone,
        "password": PASSWORD,
        "full_name": "Test User",
    }


async def _challenge(client: AsyncClient, email: str, kind: str = "verification") -> str:
    response = await client.post(
        "/auth/dev/challenge-code", json={"email": email, "kind": kind}
    )
    assert response.status_code == 200, response.text
    return response.json()["code"]


async def _register_verify(client: AsyncClient, email: str, phone: str) -> None:
    response = await client.post("/auth/register", json=_payload(email, phone))
    assert response.status_code == 201, response.text
    code = await _challenge(client, email)
    response = await client.post(
        "/auth/verify-email", json={"email": email, "code": code}
    )
    assert response.status_code == 200, response.text


def _refresh_of(response) -> str:  # noqa: ANN001
    token = response.cookies.get("amigoact_refresh")
    assert token, "refresh cookie missing"
    return token


async def test_register_verify_login_me(client: AsyncClient) -> None:
    email, phone = "happy@example.com", "0912345678"
    response = await client.post("/auth/register", json=_payload(email, phone))
    assert response.status_code == 201
    body = response.json()
    assert body["email_verified"] is False
    assert "password_hash" not in response.text

    code = await _challenge(client, email)
    response = await client.post(
        "/auth/verify-email", json={"email": email, "code": code}
    )
    assert response.json()["email_verified"] is True

    response = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "Bearer"
    assert "password_hash" not in response.text

    response = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {response.json()['access_token']}"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == email


async def test_conflicts_and_unverified_login_allowed(client: AsyncClient) -> None:
    email, phone = "taken@example.com", "0312345678"
    await client.post("/auth/register", json=_payload(email, phone))

    response = await client.post(
        "/auth/register", json=_payload(email, "0523456789")
    )
    assert response.status_code == 409
    assert response.json()["code"] == "EMAIL_TAKEN"

    response = await client.post(
        "/auth/register", json=_payload("other@example.com", phone)
    )
    assert response.status_code == 409
    assert response.json()["code"] == "PHONE_TAKEN"

    response = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200


async def test_refresh_rotation_and_reuse_burns_family(client: AsyncClient) -> None:
    email, phone = "rotate@example.com", "0777777779"
    await _register_verify(client, email, phone)
    first = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    first_token = _refresh_of(first)

    second = await client.post("/auth/refresh")
    assert second.status_code == 200
    assert _refresh_of(second) != first_token

    client.cookies.clear()
    stale = await client.post(
        "/auth/refresh", headers={"Cookie": f"amigoact_refresh={first_token}"}
    )
    assert stale.status_code == 401

    burned = await client.post("/auth/refresh")
    assert burned.status_code == 401


async def test_logout_and_logout_all(client: AsyncClient) -> None:
    email, phone = "session@example.com", "0898765432"
    await _register_verify(client, email, phone)
    logged = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    token = _refresh_of(logged)

    response = await client.post("/auth/logout")
    assert response.status_code == 204
    gone = await client.post(
        "/auth/refresh", headers={"Cookie": f"amigoact_refresh={token}"}
    )
    assert gone.status_code == 401

    first = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    access = first.json()["access_token"]
    await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    response = await client.post(
        "/auth/logout-all", headers={"Authorization": f"Bearer {access}"}
    )
    assert response.status_code == 204
    dead = await client.post("/auth/refresh")
    assert dead.status_code == 401


async def test_forgot_and_reset_password(client: AsyncClient) -> None:
    email, phone = "reset@example.com", "0934567890"
    await _register_verify(client, email, phone)
    logged = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    old_token = _refresh_of(logged)

    ghost = await client.post(
        "/auth/forgot-password", json={"email": "ghost@example.com"}
    )
    assert ghost.status_code == 202

    response = await client.post("/auth/forgot-password", json={"email": email})
    assert response.status_code == 202
    code = await _challenge(client, email, kind="reset")
    response = await client.post(
        "/auth/reset-password",
        json={"email": email, "code": code, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 200

    dead = await client.post(
        "/auth/refresh", headers={"Cookie": f"amigoact_refresh={old_token}"}
    )
    assert dead.status_code == 401
    fresh = await client.post(
        "/auth/login", json={"email": email, "password": NEW_PASSWORD}
    )
    assert fresh.status_code == 200


async def test_change_password(client: AsyncClient) -> None:
    email, phone = "change@example.com", "0945678901"
    await _register_verify(client, email, phone)
    logged = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    access = logged.json()["access_token"]
    headers = {"Authorization": f"Bearer {access}"}

    bad = await client.post(
        "/auth/change-password",
        json={"current_password": "Wrong1!xx", "new_password": NEW_PASSWORD},
        headers=headers,
    )
    assert bad.status_code == 401

    same = await client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": PASSWORD},
        headers=headers,
    )
    assert same.status_code == 400
    assert same.json()["code"] == "SAME_AS_CURRENT"

    good = await client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=headers,
    )
    assert good.status_code == 200
    survived = await client.post("/auth/refresh")
    assert survived.status_code == 200


async def test_login_rate_limited(client: AsyncClient) -> None:
    email, phone = "limited@example.com", "0956789012"
    await client.post("/auth/register", json=_payload(email, phone))
    for _ in range(5):
        response = await client.post(
            "/auth/login", json={"email": email, "password": "Wrong1!xx"}
        )
        assert response.status_code == 401
    response = await client.post(
        "/auth/login", json={"email": email, "password": "Wrong1!xx"}
    )
    assert response.status_code == 429
    assert response.json()["code"] == "TOO_MANY_REQUESTS"


def test_rate_limiter_counts_hits(clean_tables: str) -> None:
    """Counter increments per window; skips cleanly when Scylla is absent."""
    from auth.repository import CqlRateLimiter

    limiter = CqlRateLimiter(clean_tables)
    assert limiter.hit("probe:bucket", 60) == 1
    assert limiter.hit("probe:bucket", 60) == 2
    assert limiter.hit("probe:bucket", 60) == 3
