from collections.abc import Callable
from typing import Any

from tests.activity_helpers import draft, make_org, published
from tests.activity_helpers import user as activity_user
from tests.conftest import ORG_FIELDS, ApiContext
from tests.integration.test_organization_limits_api import seed_owned

Bearer = Callable[[str], dict[str, str]]


def create(api: ApiContext, headers: dict[str, str]) -> dict[str, Any]:
    response = api.client.post(
        "/organizations",
        headers=headers,
        json={**ORG_FIELDS, "name": f"CLB {api.tag}", "join_policy": "open"},
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def delete(api: ApiContext, headers: dict[str, str], slug: str) -> None:
    response = api.client.delete(f"/organizations/{slug}", headers=headers)
    assert response.status_code == 204, response.text


def trash(api: ApiContext, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = api.client.get("/organizations/mine/deleted", headers=headers)
    assert response.status_code == 200, response.text
    result: list[dict[str, Any]] = response.json()
    return result


def test_deleted_organization_is_in_the_owners_trash_only(
    api: ApiContext, bearer: Bearer
) -> None:
    owner = bearer(api.register("owner")["tokens"]["access_token"])
    other = bearer(api.register("other")["tokens"]["access_token"])
    org = create(api, owner)
    delete(api, owner, org["slug"])

    items = trash(api, owner)

    assert [item["id"] for item in items] == [org["id"]]
    assert items[0]["slug"] == org["slug"]
    assert items[0]["deleted_at"] is not None
    assert trash(api, other) == []


def test_owner_restores_and_the_organization_is_back(
    api: ApiContext, bearer: Bearer
) -> None:
    owner = bearer(api.register("owner")["tokens"]["access_token"])
    org = create(api, owner)
    delete(api, owner, org["slug"])

    response = api.client.post(
        f"/organizations/mine/deleted/{org['id']}/restore", headers=owner
    )

    assert response.status_code == 200, response.text
    assert response.json()["slug"] == org["slug"]
    assert api.client.get(f"/organizations/{org['slug']}").status_code == 200
    assert trash(api, owner) == []
    mine = api.client.get("/organizations/mine", headers=owner).json()
    assert org["slug"] in [item["slug"] for item in mine]


def test_restore_is_refused_when_the_old_slug_is_taken(
    api: ApiContext, bearer: Bearer
) -> None:
    owner = bearer(api.register("owner")["tokens"]["access_token"])
    org = create(api, owner)
    delete(api, owner, org["slug"])
    replacement = create(api, owner)
    assert replacement["slug"] == org["slug"]

    response = api.client.post(
        f"/organizations/mine/deleted/{org['id']}/restore", headers=owner
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "slug_taken"
    assert trash(api, owner)[0]["id"] == org["id"]


def test_restore_is_refused_at_the_owned_limit(api: ApiContext, bearer: Bearer) -> None:
    # seed_owned attaches to the default account, so this test registers that one.
    owner = bearer(api.register()["tokens"]["access_token"])
    org = create(api, owner)
    delete(api, owner, org["slug"])
    seed_owned(api, 5)

    response = api.client.post(
        f"/organizations/mine/deleted/{org['id']}/restore", headers=owner
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "organization_limit_reached"
    assert trash(api, owner)[0]["id"] == org["id"]


def test_only_the_owner_can_restore_and_only_from_the_trash(
    api: ApiContext, bearer: Bearer
) -> None:
    owner = bearer(api.register("owner")["tokens"]["access_token"])
    other = bearer(api.register("other")["tokens"]["access_token"])
    org = create(api, owner)
    live_restore = api.client.post(
        f"/organizations/mine/deleted/{org['id']}/restore", headers=owner
    )
    delete(api, owner, org["slug"])

    stranger = api.client.post(
        f"/organizations/mine/deleted/{org['id']}/restore", headers=other
    )

    assert live_restore.status_code == 404
    assert stranger.status_code == 404
    assert stranger.json()["detail"] == "organization_not_found"


def test_open_activity_blocks_the_delete_until_it_is_cancelled(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = activity_user(api, bearer, "owner")
    slug = make_org(api, owner)
    activity = published(api, owner, slug)

    blocked = api.client.delete(f"/organizations/{slug}", headers=owner)
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "organization_has_open_activities"
    assert api.client.get(f"/organizations/{slug}").status_code == 200

    cancelled = api.client.post(f"/activities/{activity['id']}/cancel", headers=owner)
    assert cancelled.status_code == 200, cancelled.text
    delete(api, owner, slug)


def test_draft_activities_do_not_block_the_delete(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = activity_user(api, bearer, "owner")
    slug = make_org(api, owner)
    draft(api, owner, slug)

    delete(api, owner, slug)

    assert api.client.get(f"/organizations/{slug}").status_code == 404


def test_detail_counts_open_activities_until_they_are_cancelled(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = activity_user(api, bearer, "owner")
    slug = make_org(api, owner)
    activity = published(api, owner, slug)

    before = api.client.get(f"/organizations/{slug}", headers=owner).json()
    assert before["open_activity_count"] == 1

    api.client.post(f"/activities/{activity['id']}/cancel", headers=owner)
    after = api.client.get(f"/organizations/{slug}", headers=owner).json()
    assert after["open_activity_count"] == 0
