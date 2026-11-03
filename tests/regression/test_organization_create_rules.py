from collections.abc import Callable

from tests.conftest import ORG_FIELDS, ApiContext

Bearer = Callable[[str], dict[str, str]]


def test_unverified_user_can_create_while_email_verification_is_off(
    api: ApiContext, bearer: Bearer
) -> None:
    # Temporary: email verification is not built yet, so creating does not check it.
    headers = bearer(api.register(verified=False)["tokens"]["access_token"])
    payload = {**ORG_FIELDS, "name": f"CLB {api.tag}"}

    response = api.client.post("/organizations", headers=headers, json=payload)

    assert response.status_code == 201, response.text


def test_unverified_user_can_still_join_and_browse(
    api: ApiContext, bearer: Bearer
) -> None:
    owner = bearer(api.register("owner")["tokens"]["access_token"])
    member = bearer(api.register("member", verified=False)["tokens"]["access_token"])
    slug = api.client.post(
        "/organizations",
        headers=owner,
        json={**ORG_FIELDS, "name": f"CLB {api.tag}", "join_policy": "open"},
    ).json()["slug"]

    joined = api.client.post(f"/organizations/{slug}/join", headers=member, json={})

    assert joined.status_code == 200, joined.text
    assert api.client.get("/organizations/mine", headers=member).status_code == 200
