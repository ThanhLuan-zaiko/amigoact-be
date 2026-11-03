from collections.abc import Callable

from tests.conftest import PASSWORD, ApiContext

Bearer = Callable[[str], dict[str, str]]
NEW_PASSWORD = "A-brand-new-Passw0rd"


def login(api: ApiContext, password: str, email: str | None = None) -> int:
    response = api.client.post(
        "/auth/login", json={"email": email or api.email(), "password": password}
    )
    return response.status_code


def test_profile_update_changes_only_sent_fields(
    api: ApiContext, bearer: Bearer
) -> None:
    headers = bearer(api.register()["tokens"]["access_token"])

    response = api.client.patch(
        "/account/me",
        headers=headers,
        json={"address": "Ha Noi", "date_of_birth": "2000-02-29", "gender": "other"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["address"] == "Ha Noi"
    assert body["date_of_birth"] == "2000-02-29"
    assert body["full_name"] == "Test User"

    cleared = api.client.patch("/account/me", headers=headers, json={"address": None})
    assert cleared.json()["address"] is None


def test_profile_update_rejects_taken_phone(api: ApiContext, bearer: Bearer) -> None:
    phone = "+84" + str(int(api.tag[:8], 16))[:9].zfill(9)
    api.register("first", phone=phone)
    headers = bearer(api.register("second")["tokens"]["access_token"])

    response = api.client.patch("/account/me", headers=headers, json={"phone": phone})

    assert response.status_code == 409
    assert response.json()["detail"] == "phone_taken"


def test_business_account_cannot_clear_required_fields(
    api: ApiContext, bearer: Bearer
) -> None:
    body = api.register(
        account_type="business", tax_code="0101234567", company_name="Co"
    )
    headers = bearer(body["tokens"]["access_token"])

    response = api.client.patch("/account/me", headers=headers, json={"tax_code": None})

    assert response.status_code == 422
    assert (
        api.client.get("/account/me", headers=headers).json()["tax_code"]
        == "0101234567"
    )


def test_change_password_keeps_this_session_and_ends_others(
    api: ApiContext, bearer: Bearer
) -> None:
    current = bearer(api.register()["tokens"]["access_token"])
    other_tokens = api.client.post(
        "/auth/login", json={"email": api.email(), "password": PASSWORD}
    ).json()["tokens"]

    response = api.client.post(
        "/auth/password/change",
        headers=current,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 204
    assert api.client.get("/account/me", headers=current).status_code == 200
    other = bearer(other_tokens["access_token"])
    assert api.client.get("/account/me", headers=other).status_code == 401
    assert login(api, PASSWORD) == 401
    assert login(api, NEW_PASSWORD) == 200


def test_change_password_rejects_wrong_current_password(
    api: ApiContext, bearer: Bearer
) -> None:
    headers = bearer(api.register()["tokens"]["access_token"])
    response = api.client.post(
        "/auth/password/change",
        headers=headers,
        json={"current_password": "wrong password", "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_current_password"


def test_change_password_rejects_the_current_password(
    api: ApiContext, bearer: Bearer
) -> None:
    headers = bearer(api.register()["tokens"]["access_token"])
    response = api.client.post(
        "/auth/password/change",
        headers=headers,
        json={"current_password": PASSWORD, "new_password": PASSWORD},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "same_password"
    assert login(api, PASSWORD) == 200


def test_reset_password_rejects_the_current_password(
    api: ApiContext, bearer: Bearer
) -> None:
    api.register()
    api.client.post("/auth/password/forgot", json={"email": api.email()})
    token = api.mailer.last_token()

    response = api.client.post(
        "/auth/password/reset", json={"token": token, "new_password": PASSWORD}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "same_password"
    assert login(api, PASSWORD) == 200
    # The refused link was not used up, so it still resets to a new password.
    retry = api.client.post(
        "/auth/password/reset", json={"token": token, "new_password": NEW_PASSWORD}
    )
    assert retry.status_code == 204


def test_forgot_and_reset_password(api: ApiContext, bearer: Bearer) -> None:
    access = api.register()["tokens"]["access_token"]

    forgot = api.client.post("/auth/password/forgot", json={"email": api.email()})
    assert forgot.status_code == 202
    token = api.mailer.last_token()

    reset = api.client.post(
        "/auth/password/reset", json={"token": token, "new_password": NEW_PASSWORD}
    )
    assert reset.status_code == 204
    assert login(api, NEW_PASSWORD) == 200
    assert api.client.get("/account/me", headers=bearer(access)).status_code == 401


def test_forgot_password_does_not_reveal_unknown_email(api: ApiContext) -> None:
    response = api.client.post(
        "/auth/password/forgot", json={"email": api.email("nobody")}
    )
    assert response.status_code == 202
    assert api.mailer.sent == []


def test_register_email_can_be_verified(api: ApiContext, bearer: Bearer) -> None:
    headers = bearer(api.register(verified=False)["tokens"]["access_token"])
    assert (
        api.client.get("/account/me", headers=headers).json()["email_verified_at"]
        is None
    )

    response = api.client.post(
        "/auth/email/verify", json={"token": api.mailer.last_token()}
    )

    assert response.status_code == 204
    me = api.client.get("/account/me", headers=headers).json()
    assert me["email_verified_at"] is not None


def test_resend_verification_sends_a_new_link(api: ApiContext, bearer: Bearer) -> None:
    headers = bearer(api.register(verified=False)["tokens"]["access_token"])
    first = api.mailer.last_token()

    response = api.client.post("/auth/email/resend", headers=headers)

    assert response.status_code == 202
    assert api.mailer.last_token() != first
    stale = api.client.post("/auth/email/verify", json={"token": first})
    assert stale.status_code == 400


def test_change_email_route_is_removed(api: ApiContext, bearer: Bearer) -> None:
    headers = bearer(api.register()["tokens"]["access_token"])
    response = api.client.post(
        "/account/me/email",
        headers=headers,
        json={"new_email": api.email("new"), "password": PASSWORD},
    )
    assert response.status_code == 404
    assert api.client.get("/account/me", headers=headers).json()["email"] == api.email()


def test_delete_account_route_is_removed(api: ApiContext, bearer: Bearer) -> None:
    headers = bearer(api.register()["tokens"]["access_token"])

    response = api.client.request(
        "DELETE", "/account/me", headers=headers, json={"password": PASSWORD}
    )

    assert response.status_code == 405
    assert api.client.get("/account/me", headers=headers).status_code == 200
