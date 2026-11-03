from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app import app
from src.models.organizations import Organization
from tests.conftest import ORG_FIELDS, ApiContext

Bearer = Callable[[str], dict[str, str]]


def user(api: ApiContext, bearer: Bearer, name: str) -> tuple[dict[str, str], str]:
    body = api.register(name)
    return bearer(body["tokens"]["access_token"]), body["user"]["id"]


def create(api: ApiContext, headers: dict[str, str]) -> dict[str, Any]:
    response = api.client.post(
        "/organizations",
        headers=headers,
        json={**ORG_FIELDS, "name": f"CLB {api.tag}", "join_policy": "open"},
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def stored_row(previous_slug: str) -> Organization | None:
    with Session(app.state.engine) as session:
        row = session.scalar(
            select(Organization).where(Organization.previous_slug == previous_slug)
        )
        session.expunge_all()
        return row


def test_owner_deletes_and_the_organization_disappears(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = create(api, owner)["slug"]

    response = api.client.delete(f"/organizations/{slug}", headers=owner)

    assert response.status_code == 204
    assert api.client.get(f"/organizations/{slug}").status_code == 404
    mine = api.client.get("/organizations/mine", headers=owner).json()
    assert slug not in [item["slug"] for item in mine]
    listed = api.client.get("/organizations", params={"q": api.tag}).json()["items"]
    assert slug not in [item["slug"] for item in listed]


def test_the_row_is_kept_with_its_old_slug_and_a_deleted_at(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = create(api, owner)["slug"]

    api.client.delete(f"/organizations/{slug}", headers=owner)

    row = stored_row(slug)
    assert row is not None
    assert row.deleted_at is not None
    assert row.slug.startswith("deleted-")


def test_a_new_organization_can_take_the_old_name(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = create(api, owner)["slug"]
    api.client.delete(f"/organizations/{slug}", headers=owner)

    again = create(api, owner)

    assert again["slug"] == slug


def test_only_the_owner_can_delete(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    admin, admin_id = user(api, bearer, "admin")
    member, _ = user(api, bearer, "member")
    outsider, _ = user(api, bearer, "outsider")
    slug = create(api, owner)["slug"]
    api.client.post(f"/organizations/{slug}/join", headers=admin, json={})
    api.client.post(f"/organizations/{slug}/join", headers=member, json={})
    promoted = api.client.patch(
        f"/organizations/{slug}/members/{admin_id}",
        headers=owner,
        json={"role": "admin"},
    )
    assert promoted.status_code == 204

    for headers in (admin, member, outsider):
        response = api.client.delete(f"/organizations/{slug}", headers=headers)
        assert response.status_code == 403
        assert response.json()["detail"] == "organization_forbidden"

    assert api.client.get(f"/organizations/{slug}").status_code == 200


def test_anonymous_visitor_cannot_delete(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = create(api, owner)["slug"]

    response = api.client.delete(f"/organizations/{slug}")

    assert response.status_code == 401
    assert api.client.get(f"/organizations/{slug}").status_code == 200


def test_deleting_twice_reports_not_found(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = create(api, owner)["slug"]
    api.client.delete(f"/organizations/{slug}", headers=owner)

    again = api.client.delete(f"/organizations/{slug}", headers=owner)

    assert again.status_code == 404
    assert again.json()["detail"] == "organization_not_found"
