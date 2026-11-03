from collections.abc import Callable
from pathlib import Path
from typing import Any

from tests.activity_helpers import draft, make_org
from tests.activity_helpers import user as activity_user
from tests.conftest import ORG_FIELDS, ApiContext
from tests.media_helpers import set_avatar, unique_picture, uploaded

Bearer = Callable[[str], dict[str, str]]


def create_with_logo(
    api: ApiContext, headers: dict[str, str], logo_id: str
) -> dict[str, Any]:
    response = api.client.post(
        "/organizations",
        headers=headers,
        json={**ORG_FIELDS, "name": f"CLB {api.tag}", "logo_asset_id": logo_id},
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def test_logo_of_a_deleted_organization_is_hidden_from_others_until_restored(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    # Regression guard: a deleted organization's picture must not stay public by link.
    owner, _ = activity_user(api, bearer, "owner")
    viewer, _ = activity_user(api, bearer, "viewer")
    logo = uploaded(api, owner, unique_picture())
    org = create_with_logo(api, owner, logo["id"])
    url = f"/media/{logo['id']}/file"
    assert api.client.get(url, headers=viewer).status_code == 200

    api.client.delete(f"/organizations/{org['slug']}", headers=owner)

    assert api.client.get(url, headers=viewer).status_code == 404
    assert api.client.get(url, headers=owner).status_code == 200
    restored = api.client.post(
        f"/organizations/mine/deleted/{org['id']}/restore", headers=owner
    )
    assert restored.status_code == 200, restored.text
    assert api.client.get(url, headers=viewer).status_code == 200


def test_picture_still_used_elsewhere_stays_public_after_the_delete(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    # The same file is the owner's avatar too, so hiding it would break the avatar.
    owner, _ = activity_user(api, bearer, "owner")
    viewer, _ = activity_user(api, bearer, "viewer")
    shared = uploaded(api, owner, unique_picture())
    org = create_with_logo(api, owner, shared["id"])
    assert set_avatar(api, owner, shared["id"]).status_code == 204

    api.client.delete(f"/organizations/{org['slug']}", headers=owner)

    shown = api.client.get(f"/media/{shared['id']}/file", headers=viewer)
    assert shown.status_code == 200


def test_draft_cannot_be_published_once_its_organization_is_deleted(
    api: ApiContext, bearer: Bearer
) -> None:
    # Regression guard: an activity must not open in an organization that was deleted.
    owner, _ = activity_user(api, bearer, "owner")
    slug = make_org(api, owner)
    activity = draft(api, owner, slug)
    api.client.delete(f"/organizations/{slug}", headers=owner)

    response = api.client.post(f"/activities/{activity['id']}/publish", headers=owner)

    # The public activity lookup already hides a deleted organization's activities.
    assert response.status_code == 404
    assert response.json()["detail"] == "activity_not_found"
