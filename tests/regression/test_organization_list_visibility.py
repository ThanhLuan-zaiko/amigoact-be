from collections.abc import Callable

from tests.conftest import ORG_FIELDS, ApiContext

Bearer = Callable[[str], dict[str, str]]


def make_org(api: ApiContext, headers: dict[str, str]) -> None:
    response = api.client.post(
        "/organizations", headers=headers, json={**ORG_FIELDS, "name": f"CLB {api.tag}"}
    )
    assert response.status_code == 201, response.text


def test_owned_organizations_stay_listed_by_default(
    api: ApiContext, bearer: Bearer
) -> None:
    # The home page suggestions read the list without the flag.
    owner = bearer(api.register()["tokens"]["access_token"])
    make_org(api, owner)

    response = api.client.get("/organizations", headers=owner, params={"q": api.tag})

    assert len(response.json()["items"]) == 1


def test_anonymous_visitor_with_the_flag_sees_everything(
    api: ApiContext, bearer: Bearer
) -> None:
    make_org(api, bearer(api.register()["tokens"]["access_token"]))

    response = api.client.get(
        "/organizations", params={"q": api.tag, "exclude_owned": "true"}
    )

    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


def test_invalid_flag_is_rejected(api: ApiContext) -> None:
    response = api.client.get("/organizations", params={"exclude_owned": "maybe"})

    assert response.status_code == 422
