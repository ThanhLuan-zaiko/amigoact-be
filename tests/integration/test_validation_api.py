from collections.abc import Callable

from tests.conftest import PASSWORD, ApiContext

Bearer = Callable[[str], dict[str, str]]


def issues(response_body: dict[str, list[dict[str, list[str] | str]]]) -> dict:
    return {item["loc"][-1]: item["type"] for item in response_body["detail"]}


def register_body(api: ApiContext, **extra: object) -> dict[str, object]:
    return {
        "email": api.email(),
        "password": PASSWORD,
        "full_name": "Test User",
        **extra,
    }


def test_register_stores_the_normalized_phone(api: ApiContext) -> None:
    digits = str(int(api.tag[:8], 16))[:8].zfill(8)
    body = api.register(phone=f"09{digits}")
    assert body["user"]["phone"] == f"+849{digits}"


def test_register_reports_invalid_fields_by_name(api: ApiContext) -> None:
    response = api.client.post(
        "/auth/register",
        json=register_body(
            api,
            phone="abc",
            password="Password123!",
            account_type="business",
            company_name="Co",
            tax_code="123",
        ),
    )
    assert response.status_code == 422
    assert issues(response.json()) == {
        "phone": "phone_invalid",
        "password": "password_common",
        "tax_code": "tax_code_invalid",
    }


def test_register_reports_missing_business_fields(api: ApiContext) -> None:
    response = api.client.post(
        "/auth/register", json=register_body(api, account_type="business")
    )
    assert response.status_code == 422
    assert issues(response.json()) == {
        "tax_code": "required",
        "company_name": "required",
    }


def test_profile_update_returns_422_for_bad_values(
    api: ApiContext, bearer: Bearer
) -> None:
    headers = bearer(api.register()["tokens"]["access_token"])
    response = api.client.patch(
        "/account/me",
        headers=headers,
        json={"date_of_birth": "2999-01-01", "legal_rep_id": "12345", "full_name": ""},
    )
    assert response.status_code == 422
    assert issues(response.json()) == {
        "date_of_birth": "birth_date_invalid",
        "legal_rep_id": "legal_id_invalid",
        "full_name": "string_too_short",
    }


def test_profile_update_rejects_null_full_name(api: ApiContext, bearer: Bearer) -> None:
    headers = bearer(api.register()["tokens"]["access_token"])
    response = api.client.patch(
        "/account/me", headers=headers, json={"full_name": None}
    )
    assert response.status_code == 422
    assert issues(response.json()) == {"full_name": "required"}


def test_change_password_rejects_common_password(
    api: ApiContext, bearer: Bearer
) -> None:
    headers = bearer(api.register()["tokens"]["access_token"])
    response = api.client.post(
        "/auth/password/change",
        headers=headers,
        json={"current_password": PASSWORD, "new_password": "Matkhau123!"},
    )
    assert response.status_code == 422
    assert issues(response.json()) == {"new_password": "password_common"}


def test_register_rejects_password_missing_a_character_class(api: ApiContext) -> None:
    for password in ("nouppercase1!", "NOLOWERCASE1!", "NoDigitsHere!", "NoSpecial123"):
        response = api.client.post(
            "/auth/register", json=register_body(api, password=password)
        )
        assert response.status_code == 422
        assert issues(response.json()) == {"password": "password_too_weak"}


def test_register_rejects_password_shorter_than_eight(api: ApiContext) -> None:
    response = api.client.post(
        "/auth/register", json=register_body(api, password="Ab1!xyz")
    )
    assert response.status_code == 422
    assert issues(response.json()) == {"password": "string_too_short"}


def test_change_password_rejects_personal_password(
    api: ApiContext, bearer: Bearer
) -> None:
    headers = bearer(api.register("minhanh")["tokens"]["access_token"])
    response = api.client.post(
        "/auth/password/change",
        headers=headers,
        json={
            "current_password": PASSWORD,
            "new_password": f"{api.email('minhanh').split('@')[0]}A1!",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "password_personal"


def test_reset_password_rejects_personal_password_and_keeps_the_link(
    api: ApiContext,
) -> None:
    api.register()
    api.client.post("/auth/password/forgot", json={"email": api.email()})
    token = api.mailer.last_token()

    personal = api.client.post(
        "/auth/password/reset",
        json={"token": token, "new_password": f"{api.email().split('@')[0]}A1!"},
    )
    assert personal.status_code == 422

    valid = api.client.post(
        "/auth/password/reset",
        json={"token": token, "new_password": "A-brand-new-Passw0rd"},
    )
    assert valid.status_code == 204
