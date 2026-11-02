from collections.abc import Callable
from typing import Any

from tests.conftest import ApiContext

Bearer = Callable[[str], dict[str, str]]


def user(api: ApiContext, bearer: Bearer, name: str) -> tuple[dict[str, str], str]:
    body = api.register(name)
    return bearer(body["tokens"]["access_token"]), body["user"]["id"]


def create(
    api: ApiContext, headers: dict[str, str], join_policy: str = "invite"
) -> str:
    response = api.client.post(
        "/organizations",
        headers=headers,
        json={"name": f"CLB {api.tag}", "join_policy": join_policy},
    )
    assert response.status_code == 201, response.text
    slug: str = response.json()["slug"]
    return slug


def join(
    api: ApiContext, slug: str, headers: dict[str, str], **body: Any
) -> dict[str, Any]:
    response = api.client.post(
        f"/organizations/{slug}/join", headers=headers, json=body
    )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def test_open_organization_joins_directly(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    member, _ = user(api, bearer, "member")
    slug = create(api, owner, "open")

    viewer = join(api, slug, member)

    assert viewer["status"] == "active"
    assert viewer["role"] == "member"
    assert api.client.get(f"/organizations/{slug}").json()["member_count"] == 2


def test_joining_twice_is_a_conflict(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    member, _ = user(api, bearer, "member")
    slug = create(api, owner, "open")
    join(api, slug, member)

    again = api.client.post(f"/organizations/{slug}/join", headers=member, json={})
    as_owner = api.client.post(f"/organizations/{slug}/join", headers=owner, json={})

    assert again.json()["detail"] == "already_member"
    assert as_owner.json()["detail"] == "already_member"


def test_application_waits_for_approval(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    member, member_id = user(api, bearer, "member")
    slug = create(api, owner)

    viewer = join(api, slug, member, message="Xin tham gia")

    assert viewer["status"] == "applied"
    assert viewer["role"] is None
    assert api.client.get(f"/organizations/{slug}").json()["member_count"] == 1
    again = api.client.post(f"/organizations/{slug}/join", headers=member, json={})
    assert again.json()["detail"] == "already_applied"

    pending = api.client.get(f"/organizations/{slug}/applications", headers=owner)
    assert pending.status_code == 200
    item = pending.json()["items"][0]
    assert item["user_id"] == member_id
    assert item["message"] == "Xin tham gia"

    approved = api.client.post(
        f"/organizations/{slug}/applications/{member_id}/approve", headers=owner
    )
    assert approved.status_code == 204
    assert api.client.get(f"/organizations/{slug}").json()["member_count"] == 2
    empty = api.client.get(f"/organizations/{slug}/applications", headers=owner)
    assert empty.json()["items"] == []


def test_rejected_applicant_waits_for_the_cooldown(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    member, member_id = user(api, bearer, "member")
    slug = create(api, owner)
    join(api, slug, member)

    rejected = api.client.post(
        f"/organizations/{slug}/applications/{member_id}/reject", headers=owner
    )
    retry = api.client.post(f"/organizations/{slug}/join", headers=member, json={})
    viewer = api.client.get(f"/organizations/{slug}", headers=member).json()["viewer"]

    assert rejected.status_code == 204
    assert retry.status_code == 409
    assert retry.json()["detail"] == "application_cooldown"
    assert viewer["status"] is None
    assert viewer["reapply_after"] is not None


def test_deciding_a_missing_application_returns_not_found(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, owner_id = user(api, bearer, "owner")
    slug = create(api, owner)

    response = api.client.post(
        f"/organizations/{slug}/applications/{owner_id}/approve", headers=owner
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "application_not_found"


def test_withdrawn_application_can_be_sent_again(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    member, _ = user(api, bearer, "member")
    slug = create(api, owner)
    join(api, slug, member)

    withdrawn = api.client.delete(f"/organizations/{slug}/membership", headers=member)

    assert withdrawn.status_code == 204
    assert (
        api.client.get(f"/organizations/{slug}/applications", headers=owner).json()[
            "items"
        ]
        == []
    )
    assert join(api, slug, member)["status"] == "applied"


def test_member_can_leave_and_owner_cannot(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    member, _ = user(api, bearer, "member")
    slug = create(api, owner, "open")
    join(api, slug, member)

    left = api.client.delete(f"/organizations/{slug}/membership", headers=member)
    again = api.client.delete(f"/organizations/{slug}/membership", headers=member)
    as_owner = api.client.delete(f"/organizations/{slug}/membership", headers=owner)

    assert left.status_code == 204
    assert again.json()["detail"] == "not_a_member"
    assert as_owner.json()["detail"] == "owner_cannot_leave"
    assert join(api, slug, member)["status"] == "active"


def test_members_list_shows_roles_to_members_only(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, owner_id = user(api, bearer, "owner")
    member, member_id = user(api, bearer, "member")
    outsider, _ = user(api, bearer, "outsider")
    slug = create(api, owner, "open")
    join(api, slug, member)

    listed = api.client.get(f"/organizations/{slug}/members", headers=member)
    denied = api.client.get(f"/organizations/{slug}/members", headers=outsider)

    assert listed.status_code == 200
    roles = {item["user_id"]: item["role"] for item in listed.json()["items"]}
    assert roles == {owner_id: "owner", member_id: "member"}
    assert denied.status_code == 403


def test_owner_promotes_and_demotes_an_admin(api: ApiContext, bearer: Bearer) -> None:
    owner, owner_id = user(api, bearer, "owner")
    member, member_id = user(api, bearer, "member")
    slug = create(api, owner, "open")
    join(api, slug, member)
    path = f"/organizations/{slug}/members/{member_id}"

    promoted = api.client.patch(path, headers=owner, json={"role": "admin"})
    viewer = api.client.get(f"/organizations/{slug}", headers=member).json()["viewer"]
    edit = api.client.patch(
        f"/organizations/{slug}", headers=member, json={"city": "Ha Noi"}
    )

    assert promoted.status_code == 204
    assert viewer["role"] == "admin"
    assert viewer["can_manage"] is True
    assert edit.status_code == 200

    locked = api.client.patch(
        f"/organizations/{slug}/members/{owner_id}",
        headers=owner,
        json={"role": "member"},
    )
    assert locked.json()["detail"] == "owner_role_locked"

    demoted = api.client.patch(path, headers=owner, json={"role": "member"})
    viewer = api.client.get(f"/organizations/{slug}", headers=member).json()["viewer"]
    assert demoted.status_code == 204
    assert viewer["role"] == "member"


def test_manager_removes_a_member(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    member, member_id = user(api, bearer, "member")
    slug = create(api, owner, "open")
    join(api, slug, member)

    removed = api.client.delete(
        f"/organizations/{slug}/members/{member_id}", headers=owner
    )
    missing = api.client.delete(
        f"/organizations/{slug}/members/{member_id}", headers=owner
    )

    assert removed.status_code == 204
    assert missing.json()["detail"] == "member_not_found"
    assert api.client.get(f"/organizations/{slug}").json()["member_count"] == 1
