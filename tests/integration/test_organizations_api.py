from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from src.app import app
from src.models.organizations import Organization, OrganizationMember, Role
from tests.conftest import ORG_FIELDS, ApiContext

Bearer = Callable[[str], dict[str, str]]


def create(
    api: ApiContext, headers: dict[str, str], name: str, **extra: Any
) -> dict[str, Any]:
    response = api.client.post(
        "/organizations", headers=headers, json={**ORG_FIELDS, "name": name, **extra}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_any_user_can_create_and_becomes_the_owner(
    api: ApiContext, bearer: Bearer
) -> None:
    headers = bearer(api.register()["tokens"]["access_token"])

    body = create(
        api, headers, f"CLB {api.tag}", description="Mo ta", join_policy="open"
    )

    assert body["slug"] == f"clb-{api.tag}"
    assert body["member_count"] == 1
    assert body["owner_name"] == "Test User"
    assert body["viewer"] == {
        "status": "active",
        "role": "owner",
        "can_manage": True,
        "reapply_after": None,
    }
    with app.state.engine.connect() as connection:
        org_id = connection.scalar(
            select(Organization.id).where(Organization.slug == body["slug"])
        )
        assert (
            connection.scalar(
                select(OrganizationMember.status).where(
                    OrganizationMember.org_id == org_id
                )
            )
            == "active"
        )
        assert (
            connection.scalar(select(Role.code).where(Role.org_id == org_id)) == "admin"
        )


def test_creating_requires_a_login(api: ApiContext) -> None:
    response = api.client.post("/organizations", json={**ORG_FIELDS, "name": "CLB"})

    assert response.status_code == 401


def test_same_name_gets_a_different_slug(api: ApiContext, bearer: Bearer) -> None:
    headers = bearer(api.register()["tokens"]["access_token"])

    first = create(api, headers, f"CLB {api.tag}")
    second = create(api, headers, f"CLB {api.tag}")

    assert first["slug"] != second["slug"]
    assert second["slug"].startswith(first["slug"])


def test_get_is_public_and_reports_an_empty_viewer(
    api: ApiContext, bearer: Bearer
) -> None:
    headers = bearer(api.register()["tokens"]["access_token"])
    slug = create(api, headers, f"CLB {api.tag}")["slug"]

    response = api.client.get(f"/organizations/{slug}")

    assert response.status_code == 200
    assert response.json()["viewer"]["status"] is None
    assert response.json()["viewer"]["can_manage"] is False


def test_get_unknown_slug_returns_not_found(api: ApiContext) -> None:
    response = api.client.get(f"/organizations/none-{api.tag}")

    assert response.status_code == 404
    assert response.json()["detail"] == "organization_not_found"


def test_list_searches_by_name_and_pages(api: ApiContext, bearer: Bearer) -> None:
    headers = bearer(api.register()["tokens"]["access_token"])
    for index in range(3):
        create(api, headers, f"Doi {api.tag} {index}")

    first = api.client.get("/organizations", params={"q": api.tag, "limit": 2}).json()
    second = api.client.get(
        "/organizations",
        params={"q": api.tag, "limit": 2, "offset": first["next_offset"]},
    ).json()

    assert len(first["items"]) == 2
    assert first["next_offset"] == 2
    assert len(second["items"]) == 1
    assert second["next_offset"] is None
    assert first["items"][0]["member_count"] == 1


def test_list_treats_percent_as_plain_text(api: ApiContext, bearer: Bearer) -> None:
    headers = bearer(api.register()["tokens"]["access_token"])
    create(api, headers, f"Doi {api.tag}")

    response = api.client.get("/organizations", params={"q": f"{api.tag}%"})

    assert response.json()["items"] == []


def test_mine_lists_memberships_with_roles(api: ApiContext, bearer: Bearer) -> None:
    owner = bearer(api.register("owner")["tokens"]["access_token"])
    member = bearer(api.register("member")["tokens"]["access_token"])
    open_slug = create(api, owner, f"Mo {api.tag}", join_policy="open")["slug"]
    invite_slug = create(api, owner, f"Duyet {api.tag}")["slug"]
    api.client.post(f"/organizations/{open_slug}/join", headers=member, json={})
    api.client.post(f"/organizations/{invite_slug}/join", headers=member, json={})

    mine = api.client.get("/organizations/mine", headers=member).json()
    theirs = api.client.get("/organizations/mine", headers=owner).json()

    assert {item["slug"]: (item["status"], item["role"]) for item in mine} == {
        open_slug: ("active", "member"),
        invite_slug: ("applied", None),
    }
    assert {item["role"] for item in theirs} == {"owner"}


def test_update_changes_only_sent_fields(api: ApiContext, bearer: Bearer) -> None:
    headers = bearer(api.register()["tokens"]["access_token"])
    slug = create(api, headers, f"CLB {api.tag}", description="Cu")["slug"]

    response = api.client.patch(
        f"/organizations/{slug}",
        headers=headers,
        json={
            "website": "https://example.org",
            "phone": "0912345678",
            "join_policy": "open",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["website"] == "https://example.org"
    assert body["phone"] == "+84912345678"
    assert body["join_policy"] == "open"
    assert body["description"] == "Cu"
    assert body["slug"] == slug

    cleared = api.client.patch(
        f"/organizations/{slug}", headers=headers, json={"website": None}
    )
    assert cleared.json()["website"] is None


def test_plain_member_cannot_update(api: ApiContext, bearer: Bearer) -> None:
    owner = bearer(api.register("owner")["tokens"]["access_token"])
    member = bearer(api.register("member")["tokens"]["access_token"])
    slug = create(api, owner, f"CLB {api.tag}", join_policy="open")["slug"]
    api.client.post(f"/organizations/{slug}/join", headers=member, json={})

    response = api.client.patch(
        f"/organizations/{slug}", headers=member, json={**ORG_FIELDS, "name": "Moi"}
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "organization_forbidden"
