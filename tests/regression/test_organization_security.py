from collections.abc import Callable

from sqlalchemy import update

from src.app import app
from src.models.organizations import Organization
from tests.conftest import ORG_FIELDS, ApiContext

Bearer = Callable[[str], dict[str, str]]


def user(api: ApiContext, bearer: Bearer, name: str) -> tuple[dict[str, str], str]:
    body = api.register(name)
    return bearer(body["tokens"]["access_token"]), body["user"]["id"]


def create(api: ApiContext, headers: dict[str, str], join_policy: str = "open") -> str:
    response = api.client.post(
        "/organizations",
        headers=headers,
        json={**ORG_FIELDS, "name": f"CLB {api.tag}", "join_policy": join_policy},
    )
    assert response.status_code == 201, response.text
    slug: str = response.json()["slug"]
    return slug


def test_member_count_stays_within_each_organization(
    api: ApiContext, bearer: Bearer
) -> None:
    # Regression guard: a count that is not tied to one row adds up every organization.
    owner, _ = user(api, bearer, "owner")
    member, _ = user(api, bearer, "member")
    joined = create(api, owner)
    alone = create(api, owner)
    api.client.post(f"/organizations/{joined}/join", headers=member, json={})

    assert api.client.get(f"/organizations/{joined}").json()["member_count"] == 2
    assert api.client.get(f"/organizations/{alone}").json()["member_count"] == 1
    listed = api.client.get("/organizations", params={"q": api.tag}).json()["items"]
    assert {item["slug"]: item["member_count"] for item in listed} == {
        joined: 2,
        alone: 1,
    }
    mine = api.client.get("/organizations/mine", headers=member).json()
    assert [item["member_count"] for item in mine] == [2]


def test_member_list_never_exposes_contact_details(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = create(api, owner)

    response = api.client.get(f"/organizations/{slug}/members", headers=owner)

    assert api.email("owner") not in response.text
    assert set(response.json()["items"][0]) == {
        "user_id",
        "full_name",
        "role",
        "roles",
        "joined_at",
    }


def test_application_list_never_exposes_contact_details(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    member, _ = user(api, bearer, "member")
    slug = create(api, owner, "invite")
    api.client.post(f"/organizations/{slug}/join", headers=member, json={})

    response = api.client.get(f"/organizations/{slug}/applications", headers=owner)

    assert api.email("member") not in response.text


def test_plain_member_cannot_read_or_decide_applications(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    member, _ = user(api, bearer, "member")
    applicant, applicant_id = user(api, bearer, "applicant")
    slug = create(api, owner, "open")
    api.client.post(f"/organizations/{slug}/join", headers=member, json={})
    api.client.patch(
        f"/organizations/{slug}", headers=owner, json={"join_policy": "invite"}
    )
    api.client.post(f"/organizations/{slug}/join", headers=applicant, json={})

    read = api.client.get(f"/organizations/{slug}/applications", headers=member)
    approve = api.client.post(
        f"/organizations/{slug}/applications/{applicant_id}/approve", headers=member
    )
    self_approve = api.client.post(
        f"/organizations/{slug}/applications/{applicant_id}/approve", headers=applicant
    )

    assert read.status_code == 403
    assert approve.status_code == 403
    assert self_approve.status_code == 403


def test_admin_cannot_remove_the_owner_or_another_admin(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, owner_id = user(api, bearer, "owner")
    admin, admin_id = user(api, bearer, "admin")
    other, other_id = user(api, bearer, "other")
    slug = create(api, owner)
    for headers in (admin, other):
        api.client.post(f"/organizations/{slug}/join", headers=headers, json={})
    for target in (admin_id, other_id):
        api.client.patch(
            f"/organizations/{slug}/members/{target}",
            headers=owner,
            json={"role": "admin"},
        )

    remove_owner = api.client.delete(
        f"/organizations/{slug}/members/{owner_id}", headers=admin
    )
    remove_admin = api.client.delete(
        f"/organizations/{slug}/members/{other_id}", headers=admin
    )

    assert remove_owner.json()["detail"] == "owner_cannot_be_removed"
    assert remove_admin.status_code == 403


def test_admin_cannot_grant_roles(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    admin, admin_id = user(api, bearer, "admin")
    member, member_id = user(api, bearer, "member")
    slug = create(api, owner)
    for headers in (admin, member):
        api.client.post(f"/organizations/{slug}/join", headers=headers, json={})
    api.client.patch(
        f"/organizations/{slug}/members/{admin_id}",
        headers=owner,
        json={"role": "admin"},
    )

    response = api.client.patch(
        f"/organizations/{slug}/members/{member_id}",
        headers=admin,
        json={"role": "admin"},
    )

    assert response.status_code == 403


def test_removed_member_cannot_rejoin_an_open_organization_directly(
    api: ApiContext, bearer: Bearer
) -> None:
    # Regression guard: removal must hold even when anyone may join without approval.
    owner, _ = user(api, bearer, "owner")
    member, member_id = user(api, bearer, "member")
    slug = create(api, owner)
    api.client.post(f"/organizations/{slug}/join", headers=member, json={})
    api.client.delete(f"/organizations/{slug}/members/{member_id}", headers=owner)

    response = api.client.post(f"/organizations/{slug}/join", headers=member, json={})

    assert response.json()["status"] == "applied"
    assert response.json()["role"] is None
    denied = api.client.get(f"/organizations/{slug}/members", headers=member)
    assert denied.status_code == 403


def test_removed_admin_loses_the_role_after_coming_back(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    admin, admin_id = user(api, bearer, "admin")
    slug = create(api, owner)
    api.client.post(f"/organizations/{slug}/join", headers=admin, json={})
    api.client.patch(
        f"/organizations/{slug}/members/{admin_id}",
        headers=owner,
        json={"role": "admin"},
    )
    api.client.delete(f"/organizations/{slug}/members/{admin_id}", headers=owner)
    api.client.post(f"/organizations/{slug}/join", headers=admin, json={})
    api.client.post(
        f"/organizations/{slug}/applications/{admin_id}/approve", headers=owner
    )

    viewer = api.client.get(f"/organizations/{slug}", headers=admin).json()["viewer"]

    assert viewer["role"] == "member"
    assert viewer["can_manage"] is False


def test_website_rejects_script_urls(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = create(api, owner)

    response = api.client.patch(
        f"/organizations/{slug}",
        headers=owner,
        json={"website": "javascript:alert(1)"},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "website_invalid"


def test_stale_token_is_anonymous_on_public_routes(api: ApiContext) -> None:
    owner_body = api.register("owner")
    headers = {"Authorization": f"Bearer {owner_body['tokens']['access_token']}"}
    slug = create(api, headers)

    response = api.client.get(
        f"/organizations/{slug}", headers={"Authorization": "Bearer not-a-token"}
    )

    assert response.status_code == 200
    assert response.json()["viewer"]["status"] is None


def test_suspended_organization_looks_missing(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = create(api, owner)
    with app.state.engine.begin() as connection:
        connection.execute(
            update(Organization)
            .where(Organization.slug == slug)
            .values(status="suspended")
        )

    assert api.client.get(f"/organizations/{slug}").status_code == 404
    listed = api.client.get("/organizations", params={"q": api.tag}).json()
    assert listed["items"] == []
    mine = api.client.get("/organizations/mine", headers=owner).json()
    assert mine == []


def test_bad_slug_and_search_are_rejected_not_crashed(api: ApiContext) -> None:
    assert api.client.get("/organizations/bad%00slug").status_code == 422
    assert api.client.get("/organizations", params={"q": "a\x00b"}).status_code == 422
