"""Security behavior of the account API that later changes must not break."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import update

from src.app import app
from src.auth.tokens import hash_opaque_token
from src.models.auth import AuthRefreshToken, PasswordReset
from tests.conftest import PASSWORD, ApiContext

Bearer = Callable[[str], dict[str, str]]


def test_responses_never_contain_the_password_hash(
    api: ApiContext, bearer: Bearer
) -> None:
    body = api.register()
    assert "password_hash" not in body["user"]
    me = api.client.get("/account/me", headers=bearer(body["tokens"]["access_token"]))
    assert "password_hash" not in me.json()


def test_login_failure_does_not_reveal_if_the_email_exists(api: ApiContext) -> None:
    api.register()
    wrong_password = api.client.post(
        "/auth/login", json={"email": api.email(), "password": "wrong password"}
    )
    unknown_email = api.client.post(
        "/auth/login", json={"email": api.email("nobody"), "password": "wrong password"}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_unsigned_token_is_rejected(api: ApiContext, bearer: Bearer) -> None:
    user = api.register()["user"]
    forged = jwt.encode(
        {"iss": "amigoact", "sub": user["id"], "typ": "access"},
        key="",
        algorithm="none",
    )
    response = api.client.get("/account/me", headers=bearer(forged))
    assert response.status_code == 401


def test_old_refresh_token_reuse_ends_the_session(api: ApiContext) -> None:
    old = api.register()["tokens"]["refresh_token"]
    current = api.client.post("/auth/refresh", json={"refresh_token": old}).json()
    # Move the rotation outside the grace window for parallel requests.
    with app.state.engine.begin() as connection:
        connection.execute(
            update(AuthRefreshToken)
            .where(AuthRefreshToken.token_hash == hash_opaque_token(old))
            .values(revoked_at=datetime.now(UTC) - timedelta(minutes=1))
        )

    reused = api.client.post("/auth/refresh", json={"refresh_token": old})
    assert reused.status_code == 401
    assert reused.json()["detail"] == "refresh_token_reused"

    # The token issued by the rotation dies too, because it may be the thief's.
    stolen = api.client.post(
        "/auth/refresh", json={"refresh_token": current["refresh_token"]}
    )
    assert stolen.status_code == 401


def test_parallel_refresh_inside_the_grace_window_keeps_the_session(
    api: ApiContext,
) -> None:
    old = api.register()["tokens"]["refresh_token"]
    first = api.client.post("/auth/refresh", json={"refresh_token": old})
    second = api.client.post("/auth/refresh", json={"refresh_token": old})
    assert first.status_code == second.status_code == 200
    assert first.json()["refresh_token"] != second.json()["refresh_token"]


def test_reset_token_works_only_once(api: ApiContext) -> None:
    api.register()
    api.client.post("/auth/password/forgot", json={"email": api.email()})
    token = api.mailer.last_token()
    body = {"token": token, "new_password": "A-brand-new-Passw0rd"}

    assert api.client.post("/auth/password/reset", json=body).status_code == 204
    again = api.client.post("/auth/password/reset", json=body)
    assert again.status_code == 400
    assert again.json()["detail"] == "invalid_or_expired_token"


def test_expired_reset_token_is_rejected(api: ApiContext) -> None:
    api.register()
    api.client.post("/auth/password/forgot", json={"email": api.email()})
    token = api.mailer.last_token()
    with app.state.engine.begin() as connection:
        connection.execute(
            update(PasswordReset)
            .where(PasswordReset.token_hash == hash_opaque_token(token))
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    response = api.client.post(
        "/auth/password/reset",
        json={"token": token, "new_password": "A-brand-new-Passw0rd"},
    )
    assert response.status_code == 400


def test_a_new_reset_link_invalidates_the_previous_one(api: ApiContext) -> None:
    api.register()
    api.client.post("/auth/password/forgot", json={"email": api.email()})
    first = api.mailer.last_token()
    api.client.post("/auth/password/forgot", json={"email": api.email()})

    response = api.client.post(
        "/auth/password/reset",
        json={"token": first, "new_password": "A-brand-new-Passw0rd"},
    )
    assert response.status_code == 400
    login = api.client.post(
        "/auth/login", json={"email": api.email(), "password": PASSWORD}
    )
    assert login.status_code == 200


def test_validation_errors_do_not_echo_the_password(api: ApiContext) -> None:
    secret = "lowercase-secret-1"
    response = api.client.post(
        "/auth/register",
        json={"email": api.email(), "password": secret, "full_name": "A"},
    )
    assert response.status_code == 422
    assert secret not in response.text
