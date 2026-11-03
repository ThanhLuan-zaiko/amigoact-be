from collections.abc import Callable
from pathlib import Path

from tests.activity_helpers import make_org, user
from tests.conftest import ORG_FIELDS, ApiContext
from tests.media_helpers import (
    PNG,
    WEBP,
    org_id_for,
    placed,
    set_avatar,
    stored,
    upload_video,
    uploaded,
)

Bearer = Callable[[str], dict[str, str]]


def test_avatar_shows_under_the_account_and_a_new_one_replaces_it(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, user_id = user(api, bearer, "avatar-user")
    first = uploaded(api, headers, PNG)
    assert set_avatar(api, headers, first["id"]).status_code == 204
    assert placed(media_root, user_id, "avatar") == {f"{first['id']}.png"}

    second = uploaded(api, headers, WEBP)
    assert set_avatar(api, headers, second["id"]).status_code == 204

    assert placed(media_root, user_id, "avatar") == {f"{second['id']}.webp"}
    assert len(stored(media_root, user_id, first["id"])) == 1


def test_logo_and_gallery_show_under_the_organization_folder(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, user_id = user(api, bearer, "org-user")
    slug = make_org(api, headers)
    org_id = str(org_id_for(slug))
    logo = uploaded(api, headers, PNG)
    clip = upload_video(api, headers)

    logo_set = api.client.put(
        f"/organizations/{slug}/logo", headers=headers, json={"asset_id": logo["id"]}
    )
    gallery_add = api.client.post(
        f"/organizations/{slug}/gallery", headers=headers, json={"asset_id": clip}
    )

    assert logo_set.status_code == 204
    assert gallery_add.status_code == 201, gallery_add.text
    assert placed(media_root, user_id, "organizations", org_id, "logo") == {
        f"{logo['id']}.png"
    }
    assert placed(media_root, user_id, "organizations", org_id, "gallery") == {
        f"{clip}.mp4"
    }


def test_clearing_and_removing_drops_only_the_links(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, user_id = user(api, bearer, "clearing-user")
    slug = make_org(api, headers)
    org_id = str(org_id_for(slug))
    logo = uploaded(api, headers, PNG)
    clip = upload_video(api, headers)
    api.client.put(
        f"/organizations/{slug}/logo", headers=headers, json={"asset_id": logo["id"]}
    )
    api.client.post(
        f"/organizations/{slug}/gallery", headers=headers, json={"asset_id": clip}
    )

    cleared = api.client.put(
        f"/organizations/{slug}/logo", headers=headers, json={"asset_id": None}
    )
    removed = api.client.delete(
        f"/organizations/{slug}/gallery/{clip}", headers=headers
    )

    assert cleared.status_code == 204
    assert removed.status_code == 204
    assert placed(media_root, user_id, "organizations", org_id, "logo") == set()
    assert placed(media_root, user_id, "organizations", org_id, "gallery") == set()
    # The files themselves stay, because the uploader may still use them.
    assert len(stored(media_root, user_id, logo["id"])) == 1
    assert len(stored(media_root, user_id, clip)) == 1


def test_create_shows_logo_and_gallery_under_the_organization(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, user_id = user(api, bearer, "creator")
    logo = uploaded(api, headers, PNG)
    clip = upload_video(api, headers)

    created = api.client.post(
        "/organizations",
        headers=headers,
        json={
            **ORG_FIELDS,
            "name": f"CLB {api.tag}",
            "logo_asset_id": logo["id"],
            "gallery_asset_ids": [clip],
        },
    )

    assert created.status_code == 201, created.text
    org_id = created.json()["id"]
    assert placed(media_root, user_id, "organizations", org_id, "logo") == {
        f"{logo['id']}.png"
    }
    assert placed(media_root, user_id, "organizations", org_id, "gallery") == {
        f"{clip}.mp4"
    }
