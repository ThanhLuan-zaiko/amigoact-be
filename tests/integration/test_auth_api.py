import uuid
from collections.abc import Callable

from sqlalchemy import select

from src.app import app
from src.models.auth import AuthSession, User
from tests.conftest import PASSWORD, ApiContext

Bearer = Callable[[str], dict[str, str]]


def test_register_creates_user_with_uuid7_and_argon2id(api: ApiContext) -> None:
    body = api.register()

    assert uuid.UUID(body["user"]["id"]).version == 7
    assert body["tokens"]["token_type"] == "bearer"
    with app.state.engine.connect() as connection:
        stored = connection.execute(
            select(User.password_hash).where(User.email == api.email())
        ).scalar_one()
    assert stored.startswith("$argon2id$")
    assert api.mailer.sent[-1][0] == api.email()


def test_register_rejects_duplicate_email_in_any_case(api: ApiContext) -> None:
    api.register()
    response = api.client.post(
        "/auth/register",
        json={
            "email": api.email().upper().replace("@EXAMPLE.COM", "@example.com"),
            "password": PASSWORD,
            "full_name": "Other",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "email_taken"


def test_register_rejects_weak_password(api: ApiContext) -> None:
    response = api.client.post(
        "/auth/register",
        json={"email": api.email(), "password": "short", "full_name": "A"},
    )
    assert response.status_code == 422


def test_login_returns_tokens_that_open_the_account(
    api: ApiContext, bearer: Bearer
) -> None:
    api.register()
    response = api.client.post(
        "/auth/login", json={"email": api.email(), "password": PASSWORD}
    )
    assert response.status_code == 200
    token = response.json()["tokens"]["access_token"]

    me = api.client.get("/account/me", headers=bearer(token))
    assert me.status_code == 200
    assert me.json()["email"] == api.email()
    assert me.json()["last_login_at"] is not None


def test_login_rejects_wrong_password(api: ApiContext) -> None:
    api.register()
    response = api.client.post(
        "/auth/login", json={"email": api.email(), "password": "wrong password"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_credentials"


def test_login_is_rate_limited_per_email(api: ApiContext) -> None:
    api.register()
    credentials = {"email": api.email(), "password": "wrong password"}
    for _ in range(10):
        assert api.client.post("/auth/login", json=credentials).status_code == 401
    response = api.client.post("/auth/login", json=credentials)
    assert response.status_code == 429
    assert "retry-after" in response.headers


def test_account_me_requires_a_token(api: ApiContext, bearer: Bearer) -> None:
    assert api.client.get("/account/me").status_code == 401
    assert api.client.get("/account/me", headers=bearer("garbage")).status_code == 401


def test_refresh_rotates_the_token(api: ApiContext, bearer: Bearer) -> None:
    tokens = api.register()["tokens"]
    response = api.client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 200
    rotated = response.json()
    assert rotated["refresh_token"] != tokens["refresh_token"]
    me = api.client.get("/account/me", headers=bearer(rotated["access_token"]))
    assert me.status_code == 200


def test_refresh_rejects_unknown_token(api: ApiContext) -> None:
    response = api.client.post("/auth/refresh", json={"refresh_token": "unknown"})
    assert response.status_code == 401


def test_logout_ends_the_session(api: ApiContext, bearer: Bearer) -> None:
    tokens = api.register()["tokens"]
    headers = bearer(tokens["access_token"])

    assert api.client.post("/auth/logout", headers=headers).status_code == 204

    assert api.client.get("/account/me", headers=headers).status_code == 401
    refreshed = api.client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 401


def test_logout_all_ends_every_session(api: ApiContext, bearer: Bearer) -> None:
    first = api.register()["tokens"]["access_token"]
    second = api.client.post(
        "/auth/login", json={"email": api.email(), "password": PASSWORD}
    ).json()["tokens"]["access_token"]

    response = api.client.post("/auth/logout-all", headers=bearer(first))

    assert response.status_code == 204
    assert api.client.get("/account/me", headers=bearer(first)).status_code == 401
    assert api.client.get("/account/me", headers=bearer(second)).status_code == 401


def test_sessions_are_listed_and_can_be_revoked(
    api: ApiContext, bearer: Bearer
) -> None:
    first = api.register()["tokens"]["access_token"]
    second = api.client.post(
        "/auth/login", json={"email": api.email(), "password": PASSWORD}
    ).json()["tokens"]["access_token"]

    listed = api.client.get("/auth/sessions", headers=bearer(first)).json()
    assert len(listed) == 2
    other = next(item for item in listed if not item["is_current"])

    revoked = api.client.delete(
        f"/auth/sessions/{other['session_id']}", headers=bearer(first)
    )
    assert revoked.status_code == 204
    assert api.client.get("/account/me", headers=bearer(second)).status_code == 401
    assert api.client.get("/account/me", headers=bearer(first)).status_code == 200

    with app.state.engine.connect() as connection:
        revoked_at = connection.execute(
            select(AuthSession.revoked_at).where(
                AuthSession.session_id == uuid.UUID(other["session_id"])
            )
        ).scalar_one()
    assert revoked_at is not None


def test_session_of_another_user_cannot_be_revoked(
    api: ApiContext, bearer: Bearer
) -> None:
    mine = api.register("mine")["tokens"]["access_token"]
    theirs = api.register("theirs")["tokens"]["access_token"]
    other = api.client.get("/auth/sessions", headers=bearer(theirs)).json()[0]

    response = api.client.delete(
        f"/auth/sessions/{other['session_id']}", headers=bearer(mine)
    )

    assert response.status_code == 404
    assert api.client.get("/account/me", headers=bearer(theirs)).status_code == 200
