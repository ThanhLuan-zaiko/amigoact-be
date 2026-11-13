"""Hidden organizations must stay out of the directory for every viewer, and the flag must
reject values that are not real booleans."""

from tests.activity_helpers import Bearer, user
from tests.conftest import ORG_FIELDS, ApiContext


def _directory(api: ApiContext, headers: dict[str, str] | None = None) -> list[object]:
    response = api.client.get(
        "/organizations", params={"limit": 50}, headers=headers or {}
    )
    assert response.status_code == 200, response.text
    return [item["slug"] for item in response.json()["items"]]


def test_hidden_organization_is_missing_for_guests_members_and_owner(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "hidesec")
    viewer, _ = user(api, bearer, "hidesecview")
    name = f"An danh {api.tag}"
    org = api.client.post(
        "/organizations",
        headers=owner,
        json={**ORG_FIELDS, "name": name, "join_policy": "open"},
    ).json()
    api.client.patch(
        f"/organizations/{org['slug']}",
        headers=owner,
        json={"listed_publicly": False},
    )

    assert org["slug"] not in _directory(api)
    assert org["slug"] not in _directory(api, viewer)
    assert org["slug"] not in _directory(api, owner)
    search = api.client.get("/organizations", params={"q": name}, headers=owner)
    assert org["slug"] not in [item["slug"] for item in search.json()["items"]]


def test_listing_flag_rejects_null_and_text(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "hidenull")
    org = api.client.post(
        "/organizations",
        headers=owner,
        json={**ORG_FIELDS, "name": f"Nhom null {api.tag}", "join_policy": "open"},
    ).json()
    path = f"/organizations/{org['slug']}"

    as_null = api.client.patch(path, headers=owner, json={"listed_publicly": None})
    as_text = api.client.patch(path, headers=owner, json={"listed_publicly": "false"})

    assert as_null.status_code == 422
    assert as_text.status_code == 422
    assert org["slug"] in _directory(api)
