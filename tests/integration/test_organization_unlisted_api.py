"""An owner or admin can hide an organization from the public directory."""

from tests.activity_helpers import Bearer, user
from tests.conftest import ORG_FIELDS, ApiContext


def _create(api: ApiContext, headers: dict[str, str], name: str) -> dict[str, object]:
    response = api.client.post(
        "/organizations",
        headers=headers,
        json={**ORG_FIELDS, "name": name, "join_policy": "open"},
    )
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


def _listed_slugs(api: ApiContext, name: str) -> list[object]:
    response = api.client.get("/organizations", params={"q": name})
    assert response.status_code == 200, response.text
    return [item["slug"] for item in response.json()["items"]]


def test_owner_hides_and_shows_organization_in_directory(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "unlistown")
    name = f"Nhom an {api.tag}"
    org = _create(api, owner, name)
    slug = org["slug"]
    assert slug in _listed_slugs(api, name)

    hidden = api.client.patch(
        f"/organizations/{slug}", headers=owner, json={"listed_publicly": False}
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["listed_publicly"] is False
    assert slug not in _listed_slugs(api, name)

    shown = api.client.patch(
        f"/organizations/{slug}", headers=owner, json={"listed_publicly": True}
    )
    assert shown.status_code == 200, shown.text
    assert slug in _listed_slugs(api, name)


def test_hidden_organization_still_opens_by_its_address(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "unlistlink")
    name = f"Nhom link {api.tag}"
    org = _create(api, owner, name)
    api.client.patch(
        f"/organizations/{org['slug']}",
        headers=owner,
        json={"listed_publicly": False},
    )

    response = api.client.get(f"/organizations/{org['slug']}")

    assert response.status_code == 200
    assert response.json()["listed_publicly"] is False


def test_non_manager_cannot_change_listing(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "unlistlead")
    stranger, _ = user(api, bearer, "unliststr")
    org = _create(api, owner, f"Nhom quyen {api.tag}")

    response = api.client.patch(
        f"/organizations/{org['slug']}",
        headers=stranger,
        json={"listed_publicly": False},
    )

    assert response.status_code == 403
