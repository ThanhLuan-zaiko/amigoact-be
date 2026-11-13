from tests.conftest import ApiContext
from tests.role_helpers import Bearer, give, join, new_role, person, team


def names(api: ApiContext, slug: str, headers: dict[str, str]) -> list[str]:
    items = api.client.get(f"/organizations/{slug}/roles", headers=headers).json()
    return [item["name"] for item in items["items"]]


def test_owner_creates_edits_and_deletes_a_role(
    api: ApiContext, bearer: Bearer
) -> None:
    slug, owner, _, _ = team(api, bearer)
    base = f"/organizations/{slug}/roles"

    role = new_role(api, slug, owner, "Moderator", "posts.pin", color="#AABBCC")
    assert role["color"] == "#aabbcc"
    assert role["permissions"] == ["posts.pin"]
    assert role["member_count"] == 0

    patched = api.client.patch(
        f"{base}/{role['id']}",
        headers=owner,
        json={"name": "Mods", "permissions": ["posts.pin", "channels.create"]},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "Mods"
    assert patched.json()["permissions"] == ["channels.create", "posts.pin"]
    listed = api.client.get(base, headers=owner).json()
    assert "administrator" in listed["catalog"]
    assert names(api, slug, owner) == ["Admin", "Mods"]

    gone = api.client.delete(f"{base}/{role['id']}", headers=owner)
    assert gone.status_code == 204
    assert names(api, slug, owner) == ["Admin"]


def test_new_organization_has_an_editable_admin_role(
    api: ApiContext, bearer: Bearer
) -> None:
    slug, owner, _, _ = team(api, bearer)

    items = api.client.get(f"/organizations/{slug}/roles", headers=owner).json()[
        "items"
    ]

    assert [item["name"] for item in items] == ["Admin"]
    admin = items[0]
    assert "roles.create" not in admin["permissions"]
    assert "administrator" not in admin["permissions"]
    assert "activities.create" in admin["permissions"]
    assert admin["below_you"] is True


def test_roles_are_assigned_and_shown_on_members(
    api: ApiContext, bearer: Bearer
) -> None:
    slug, owner, member, member_id = team(api, bearer)
    role = new_role(api, slug, owner, "Reviewers", "applications.review")

    done = give(api, slug, owner, member_id, role["id"])

    assert done.status_code == 200, done.text
    assert [badge["name"] for badge in done.json()] == ["Reviewers"]
    members = api.client.get(f"/organizations/{slug}/members", headers=owner).json()
    mine = next(m for m in members["items"] if m["user_id"] == member_id)
    assert mine["role"] == "admin"
    assert [badge["id"] for badge in mine["roles"]] == [role["id"]]
    viewer = api.client.get(f"/organizations/{slug}", headers=member).json()["viewer"]
    assert viewer["permissions"] == ["applications.review"]
    assert viewer["can_manage"] is True

    cleared = give(api, slug, owner, member_id)
    assert cleared.json() == []
    after = api.client.get(f"/organizations/{slug}", headers=member).json()["viewer"]
    assert after["role"] == "member"
    assert after["permissions"] == []


def test_a_role_grants_only_the_permission_it_names(
    api: ApiContext, bearer: Bearer
) -> None:
    slug, owner, member, member_id = team(api, bearer)
    reviewer = new_role(api, slug, owner, "Reviewers", "applications.review")
    give(api, slug, owner, member_id, reviewer["id"])

    applications = api.client.get(f"/organizations/{slug}/applications", headers=member)
    profile = api.client.patch(
        f"/organizations/{slug}", headers=member, json={"city": "Hue"}
    )
    new = api.client.post(
        f"/organizations/{slug}/roles", headers=member, json={"name": "X"}
    )

    assert applications.status_code == 200
    assert profile.status_code == 403
    assert new.status_code == 403


def test_editing_a_role_changes_what_its_holders_can_do(
    api: ApiContext, bearer: Bearer
) -> None:
    slug, owner, member, member_id = team(api, bearer)
    role = new_role(api, slug, owner, "Editors", "organization.update")
    give(api, slug, owner, member_id, role["id"])
    url = f"/organizations/{slug}"
    assert (
        api.client.patch(url, headers=member, json={"city": "Hue"}).status_code == 200
    )

    api.client.patch(
        f"{url}/roles/{role['id']}", headers=owner, json={"permissions": []}
    )

    assert (
        api.client.patch(url, headers=member, json={"city": "Vinh"}).status_code == 403
    )
    assert api.client.get(url, headers=member).json()["viewer"]["role"] == "member"


def test_deleting_a_role_removes_it_from_members(
    api: ApiContext, bearer: Bearer
) -> None:
    slug, owner, member, member_id = team(api, bearer)
    role = new_role(api, slug, owner, "Temp", "organization.update")
    give(api, slug, owner, member_id, role["id"])

    api.client.delete(f"/organizations/{slug}/roles/{role['id']}", headers=owner)

    viewer = api.client.get(f"/organizations/{slug}", headers=member).json()["viewer"]
    assert viewer["permissions"] == []
    members = api.client.get(f"/organizations/{slug}/members", headers=owner).json()
    assert all(m["roles"] == [] for m in members["items"])


def test_reorder_roles_changes_positions(api: ApiContext, bearer: Bearer) -> None:
    slug, owner, _, _ = team(api, bearer)
    low = new_role(api, slug, owner, "Low")
    high = new_role(api, slug, owner, "High")
    base = f"/organizations/{slug}/roles"
    admin = api.client.get(base, headers=owner).json()["items"][0]

    moved = api.client.put(
        f"{base}/order",
        headers=owner,
        json={"role_ids": [admin["id"], low["id"], high["id"]]},
    )

    assert moved.status_code == 200, moved.text
    assert [item["name"] for item in moved.json()["items"]] == ["Admin", "Low", "High"]


def test_role_names_are_unique_per_organization(
    api: ApiContext, bearer: Bearer
) -> None:
    slug, owner, _, _ = team(api, bearer)
    new_role(api, slug, owner, "Crew")

    taken = api.client.post(
        f"/organizations/{slug}/roles", headers=owner, json={"name": "crew"}
    )

    assert taken.status_code == 409
    assert taken.json()["detail"] == "role_name_taken"


def test_only_members_read_the_role_list(api: ApiContext, bearer: Bearer) -> None:
    slug, _, member, _ = team(api, bearer)
    outsider, _ = person(api, bearer, "outsider")
    url = f"/organizations/{slug}/roles"

    assert api.client.get(url, headers=member).status_code == 200
    assert api.client.get(url, headers=outsider).status_code == 403
    join(api, slug, outsider)
    assert api.client.get(url, headers=outsider).status_code == 200


def test_a_role_can_create_without_being_able_to_update_or_delete(
    api: ApiContext, bearer: Bearer
) -> None:
    slug, owner, member, member_id = team(api, bearer)
    role = new_role(api, slug, owner, "Planners", "activities.create")
    give(api, slug, owner, member_id, role["id"])
    body = {
        "title": "Don rac",
        "description": "Mo ta",
        "location": "Ha Noi",
        "start_at": "2099-01-01T01:00:00Z",
        "end_at": "2099-01-01T05:00:00Z",
        "max_participants": 10,
        "city": "Ha Noi",
        "hours_awarded": 2,
    }

    created = api.client.post(
        f"/organizations/{slug}/activities", headers=member, json=body
    )

    assert created.status_code == 201, created.text
    activity_id = created.json()["id"]
    assert (
        api.client.patch(
            f"/activities/{activity_id}", headers=member, json={"title": "Moi"}
        ).status_code
        == 403
    )
    assert (
        api.client.delete(f"/activities/{activity_id}", headers=member).status_code
        == 403
    )


def test_role_actions_are_separate_permissions(api: ApiContext, bearer: Bearer) -> None:
    slug, owner, member, member_id = team(api, bearer)
    maker = new_role(api, slug, owner, "Makers", "roles.create")
    victim = new_role(api, slug, owner, "Victim")
    give(api, slug, owner, member_id, maker["id"])
    base = f"/organizations/{slug}/roles"

    made = api.client.post(base, headers=member, json={"name": "Fresh"})
    edited = api.client.patch(
        f"{base}/{made.json()['id']}", headers=member, json={"name": "Fresher"}
    )
    removed = api.client.delete(f"{base}/{victim['id']}", headers=member)

    assert made.status_code == 201
    assert edited.status_code == 403
    assert removed.status_code == 403
