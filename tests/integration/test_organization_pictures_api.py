from typing import Any

from tests.activity_helpers import Bearer, user
from tests.conftest import ApiContext
from tests.media_helpers import MP4, PNG, uploaded
from tests.post_helpers import join, open_org, promote


def _detail(api: ApiContext, slug: str) -> dict[str, Any]:
    response = api.client.get(f"/organizations/{slug}")
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def _choose(api: ApiContext, headers: Any, slug: str, **body: Any) -> Any:
    return api.client.put(f"/organizations/{slug}/pictures", headers=headers, json=body)


def test_swap_logo_and_cover_in_one_request(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "picswap")
    slug = open_org(api, owner)
    first = uploaded(api, owner, PNG + b"1")["id"]
    second = uploaded(api, owner, PNG + b"2")["id"]
    assert (
        _choose(
            api, owner, slug, logo_asset_id=first, cover_asset_id=second
        ).status_code
        == 204
    )

    response = _choose(api, owner, slug, logo_asset_id=second, cover_asset_id=first)

    assert response.status_code == 204
    detail = _detail(api, slug)
    assert detail["logo_url"] == f"/media/{second}/file"
    assert detail["cover_url"] == f"/media/{first}/file"


def test_gallery_picture_from_another_manager_becomes_logo(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "picgal")
    admin, admin_id = user(api, bearer, "picgaladm")
    slug = open_org(api, owner)
    join(api, slug, admin)
    promote(api, slug, owner, admin_id)
    photo = uploaded(api, admin, PNG + b"3")["id"]
    added = api.client.post(
        f"/organizations/{slug}/gallery", headers=admin, json={"asset_id": photo}
    )
    assert added.status_code == 201

    response = _choose(api, owner, slug, logo_asset_id=photo)

    assert response.status_code == 204
    detail = _detail(api, slug)
    assert detail["logo_url"] == f"/media/{photo}/file"
    assert detail["cover_url"] is None
    assert api.client.get(f"/media/{photo}/file").status_code == 200


def test_left_out_role_keeps_its_picture(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "pickeep")
    slug = open_org(api, owner)
    cover = uploaded(api, owner, PNG + b"4")["id"]
    logo = uploaded(api, owner, PNG + b"5")["id"]
    assert _choose(api, owner, slug, cover_asset_id=cover).status_code == 204

    assert _choose(api, owner, slug, logo_asset_id=logo).status_code == 204

    assert _detail(api, slug)["cover_url"] == f"/media/{cover}/file"
    assert _choose(api, owner, slug, cover_asset_id=None).status_code == 204
    assert _detail(api, slug)["cover_url"] is None


def test_gallery_video_cannot_be_logo(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "picvid")
    slug = open_org(api, owner)
    video = uploaded(api, owner, MP4)["id"]
    api.client.post(
        f"/organizations/{slug}/gallery", headers=owner, json={"asset_id": video}
    )

    response = _choose(api, owner, slug, logo_asset_id=video)

    assert response.status_code == 415
    assert response.json()["detail"] == "unsupported_media_type"


def test_replaced_logo_moves_to_the_gallery(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "picmove")
    slug = open_org(api, owner)
    old = uploaded(api, owner, PNG + b"6")["id"]
    new = uploaded(api, owner, PNG + b"7")["id"]
    assert _choose(api, owner, slug, logo_asset_id=old).status_code == 204

    assert _choose(api, owner, slug, logo_asset_id=new).status_code == 204

    gallery = api.client.get(f"/organizations/{slug}/gallery").json()
    assert [item["id"] for item in gallery] == [old]
    assert _choose(api, owner, slug, logo_asset_id=old).status_code == 204
    gallery = api.client.get(f"/organizations/{slug}/gallery").json()
    assert {item["id"] for item in gallery} == {old, new}
