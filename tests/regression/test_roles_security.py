"""Role rules that keep a lower role from taking over a higher one."""

from tests.conftest import ApiContext
from tests.role_helpers import Bearer, give, join, new_role, person, team


def with_manager(
    api: ApiContext, bearer: Bearer
) -> tuple[str, dict[str, str], dict[str, str], str, dict[str, str]]:
    """Owner, a member who holds the role permissions, and a plain member."""
    slug, owner, manager, manager_id = team(api, bearer)
    plain, plain_id = person(api, bearer, "plain")
    join(api, slug, plain)
    role = new_role(
        api,
        slug,
        owner,
        "Lead",
        "roles.create",
        "roles.update",
        "roles.delete",
        "roles.assign",
        "members.remove",
    )
    assert give(api, slug, owner, manager_id, role["id"]).status_code == 200
    return slug, owner, manager, plain_id, plain


def test_a_role_manager_cannot_grant_a_permission_they_lack(
    api: ApiContext, bearer: Bearer
) -> None:
    slug, _, manager, _, _ = with_manager(api, bearer)
    url = f"/organizations/{slug}/roles"

    asked = api.client.post(
        url, headers=manager, json={"name": "Boss", "permissions": ["posts.pin"]}
    )
    admin = api.client.post(
        url, headers=manager, json={"name": "Root", "permissions": ["administrator"]}
    )

    assert asked.status_code == 403
    assert asked.json()["detail"] == "permission_not_held"
    assert admin.json()["detail"] == "permission_not_held"


def test_a_role_manager_cannot_edit_their_own_or_a_higher_role(
    api: ApiContext, bearer: Bearer
) -> None:
    slug, owner, manager, _, _ = with_manager(api, bearer)
    roles = api.client.get(f"/organizations/{slug}/roles", headers=owner).json()
    by_name = {role["name"]: role for role in roles["items"]}

    own = api.client.patch(
        f"/organizations/{slug}/roles/{by_name['Lead']['id']}",
        headers=manager,
        json={"permissions": ["roles.create", "roles.update"]},
    )
    higher = api.client.delete(
        f"/organizations/{slug}/roles/{by_name['Admin']['id']}", headers=manager
    )

    assert own.status_code == 403
    assert own.json()["detail"] == "role_hierarchy"
    assert higher.status_code == 403
    assert higher.json()["detail"] == "role_hierarchy"


def test_a_role_manager_cannot_give_a_role_at_or_above_their_own(
    api: ApiContext, bearer: Bearer
) -> None:
    slug, owner, manager, _, plain = with_manager(api, bearer)
    plain_id = api.client.get("/account/me", headers=plain).json()["id"]
    roles = api.client.get(f"/organizations/{slug}/roles", headers=owner).json()
    by_name = {role["name"]: role for role in roles["items"]}

    admin = give(api, slug, manager, plain_id, by_name["Admin"]["id"])
    lead = give(api, slug, manager, plain_id, by_name["Lead"]["id"])

    assert admin.status_code == 403
    assert lead.status_code == 403
    below = new_role(api, slug, manager, "Helper", "members.remove")
    assert give(api, slug, manager, plain_id, below["id"]).status_code == 200


def test_a_role_manager_cannot_change_or_remove_a_higher_member(
    api: ApiContext, bearer: Bearer
) -> None:
    slug, owner, manager, _, _ = with_manager(api, bearer)
    boss, boss_id = person(api, bearer, "boss")
    join(api, slug, boss)
    roles = api.client.get(f"/organizations/{slug}/roles", headers=owner).json()
    admin = next(r for r in roles["items"] if r["name"] == "Admin")
    give(api, slug, owner, boss_id, admin["id"])

    changed = give(api, slug, manager, boss_id)
    removed = api.client.delete(
        f"/organizations/{slug}/members/{boss_id}", headers=manager
    )

    assert changed.status_code == 403
    assert removed.status_code == 403
    members = api.client.get(f"/organizations/{slug}/members", headers=owner).json()
    assert any(m["user_id"] == boss_id for m in members["items"])


def test_nobody_changes_the_roles_of_the_owner_or_themselves(
    api: ApiContext, bearer: Bearer
) -> None:
    slug, owner, manager, _, _ = with_manager(api, bearer)
    owner_id = api.client.get("/account/me", headers=owner).json()["id"]
    manager_id = api.client.get("/account/me", headers=manager).json()["id"]

    on_owner = give(api, slug, owner, owner_id)
    on_self = give(api, slug, manager, manager_id)

    assert on_owner.json()["detail"] == "owner_role_locked"
    assert on_self.status_code == 403


def test_a_plain_member_cannot_touch_roles(api: ApiContext, bearer: Bearer) -> None:
    slug, owner, _, plain_id, plain = with_manager(api, bearer)
    roles = api.client.get(f"/organizations/{slug}/roles", headers=owner).json()
    first = roles["items"][0]["id"]
    base = f"/organizations/{slug}/roles"

    attempts = [
        api.client.post(base, headers=plain, json={"name": "Mine"}),
        api.client.patch(f"{base}/{first}", headers=plain, json={"name": "Mine"}),
        api.client.delete(f"{base}/{first}", headers=plain),
        api.client.put(f"{base}/order", headers=plain, json={"role_ids": [first]}),
        give(api, slug, plain, plain_id, first),
    ]

    assert [r.status_code for r in attempts] == [403, 403, 403, 403, 403]


def test_a_role_of_another_organization_is_not_found(
    api: ApiContext, bearer: Bearer
) -> None:
    slug, owner, _, member_id = team(api, bearer)
    other_owner, _ = person(api, bearer, "other")
    other_slug = api.client.post(
        "/organizations",
        headers=other_owner,
        json={
            "name": f"Other {api.tag}",
            "description": "x",
            "email": "o@example.com",
            "phone": "0912345678",
            "city": "Ha Noi",
        },
    ).json()["slug"]
    foreign = new_role(api, other_slug, other_owner, "Foreign", "posts.pin")

    patched = api.client.patch(
        f"/organizations/{slug}/roles/{foreign['id']}",
        headers=owner,
        json={"name": "Taken"},
    )
    assigned = give(api, slug, owner, member_id, foreign["id"])

    assert patched.status_code == 404
    assert assigned.status_code == 404


def test_losing_the_only_staff_role_ends_manager_access(
    api: ApiContext, bearer: Bearer
) -> None:
    slug, owner, manager, _, _ = with_manager(api, bearer)
    manager_id = api.client.get("/account/me", headers=manager).json()["id"]
    assert (
        api.client.get(
            f"/organizations/{slug}/applications", headers=manager
        ).status_code
        == 403
    )
    review = new_role(api, slug, owner, "Review", "applications.review")
    give(api, slug, owner, manager_id, review["id"])
    assert (
        api.client.get(
            f"/organizations/{slug}/applications", headers=manager
        ).status_code
        == 200
    )

    api.client.delete(f"/organizations/{slug}/roles/{review['id']}", headers=owner)

    assert (
        api.client.get(
            f"/organizations/{slug}/applications", headers=manager
        ).status_code
        == 403
    )


def test_a_member_who_left_loses_their_roles(api: ApiContext, bearer: Bearer) -> None:
    slug, owner, member, member_id = team(api, bearer)
    role = new_role(api, slug, owner, "Staff", "applications.review")
    give(api, slug, owner, member_id, role["id"])

    api.client.delete(f"/organizations/{slug}/membership", headers=member)

    again = give(api, slug, owner, member_id, role["id"])
    assert again.status_code == 404
    assert again.json()["detail"] == "member_not_found"


def test_role_bodies_reject_bad_input(api: ApiContext, bearer: Bearer) -> None:
    slug, owner, _, member_id = team(api, bearer)
    url = f"/organizations/{slug}/roles"

    bad = [
        {"name": "A", "color": "red"},
        {"name": "A", "color": "#12345"},
        {"name": "A", "permissions": ["root"]},
        {"name": "A", "permissions": ["posts.pin", "posts.pin"]},
        {"name": "A", "position": 99},
        {"name": "   "},
        {"name": "###"},
        {"name": "A\x00B"},
    ]

    for body in bad:
        response = api.client.post(url, headers=owner, json=body)
        assert response.status_code == 422, body
    assert give(api, slug, owner, member_id, "not-a-uuid").status_code == 422
