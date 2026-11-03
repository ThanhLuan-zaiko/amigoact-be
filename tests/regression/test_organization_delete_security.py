import uuid
from collections.abc import Callable
from pathlib import Path

from src.models.media import MediaAsset
from src.models.organizations import OrganizationMember
from tests.activity_helpers import make_org, published, user
from tests.conftest import ORG_FIELDS, ApiContext
from tests.media_helpers import PNG, db_row, org_id_for, stored, uploaded

Bearer = Callable[[str], dict[str, str]]


def test_deleted_organization_looks_missing_to_everyone(
    api: ApiContext, bearer: Bearer
) -> None:
    # Regression guard: a deleted row must not leak through members, joins or galleries.
    owner, _ = user(api, bearer, "owner")
    member, _ = user(api, bearer, "member")
    outsider, _ = user(api, bearer, "outsider")
    slug = make_org(api, owner)
    api.client.delete(f"/organizations/{slug}", headers=owner)

    for headers in (owner, member, outsider):
        assert (
            api.client.get(f"/organizations/{slug}", headers=headers).status_code == 404
        )
        assert (
            api.client.get(
                f"/organizations/{slug}/members", headers=headers
            ).status_code
            == 404
        )
        assert api.client.get(f"/organizations/{slug}/gallery").status_code == 404
        assert (
            api.client.post(
                f"/organizations/{slug}/join", headers=headers, json={}
            ).status_code
            == 404
        )
        assert (
            api.client.patch(
                f"/organizations/{slug}", headers=headers, json={"name": "Moi ten"}
            ).status_code
            == 404
        )


def test_activities_of_a_deleted_organization_are_hidden(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = make_org(api, owner)
    activity = published(api, owner, slug)
    assert api.client.get(f"/activities/{activity['id']}").status_code == 200
    # A published activity blocks the delete, so cancel it first.
    cancelled = api.client.post(f"/activities/{activity['id']}/cancel", headers=owner)
    assert cancelled.status_code == 200, cancelled.text

    api.client.delete(f"/organizations/{slug}", headers=owner)

    assert api.client.get(f"/activities/{activity['id']}").status_code == 404
    assert api.client.get(f"/organizations/{slug}/activities").status_code == 404


def test_deleting_keeps_members_and_the_logo_file(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    # A soft delete must not touch the data, so a later restore has everything it needs.
    owner, owner_id = user(api, bearer, "owner")
    logo = uploaded(api, owner, PNG + api.tag.encode())
    body = {**ORG_FIELDS, "name": f"CLB {api.tag}", "logo_asset_id": logo["id"]}
    slug = api.client.post("/organizations", headers=owner, json=body).json()["slug"]
    org_id = org_id_for(slug)

    api.client.delete(f"/organizations/{slug}", headers=owner)

    member = db_row(OrganizationMember, (org_id, uuid.UUID(owner_id)))
    asset = db_row(MediaAsset, uuid.UUID(logo["id"]))
    assert member is not None and member.status == "active"
    assert asset is not None and asset.upload_status == "active"
    assert len(stored(media_root, owner_id, logo["id"])) == 1
