from tests.conftest import PASSWORD, ApiContext


def test_one_phone_number_cannot_register_in_two_forms(api: ApiContext) -> None:
    # Regression guard: 09... and +849... used to count as different numbers.
    digits = str(int(api.tag[:8], 16))[:8].zfill(8)
    api.register("first", phone=f"09{digits}")

    response = api.client.post(
        "/auth/register",
        json={
            "email": api.email("second"),
            "password": PASSWORD,
            "full_name": "Other",
            "phone": f"+849{digits}",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "phone_taken"
