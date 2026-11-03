from collections.abc import Callable
from pathlib import Path

from tests.activity_helpers import make_org, user
from tests.conftest import ApiContext
from tests.media_helpers import PNG, WEBP, set_avatar, stored, uploaded

Bearer = Callable[[str], dict[str, str]]


def files_in(media_root: Path) -> set[str]:
    return {entry.name for entry in media_root.iterdir()}


def test_upload_is_stored_flat_under_its_asset_id(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, _ = user(api, bearer, "uploader")

    body = uploaded(api, headers, PNG)

    assert files_in(media_root) == {f"{body['id']}.png"}
    assert all(entry.is_file() for entry in media_root.iterdir())


def test_using_a_file_in_several_places_keeps_one_copy(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, _ = user(api, bearer, "double-use")
    slug = make_org(api, headers)
    body = uploaded(api, headers, PNG)

    assert set_avatar(api, headers, body["id"]).status_code == 204
    logo = api.client.put(
        f"/organizations/{slug}/logo", headers=headers, json={"asset_id": body["id"]}
    )

    assert logo.status_code == 204, logo.text
    assert files_in(media_root) == {f"{body['id']}.png"}
    assert len(stored(media_root, body["id"])) == 1


def test_a_second_picture_is_stored_beside_the_first(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, _ = user(api, bearer, "avatar-user")
    first = uploaded(api, headers, PNG)
    second = uploaded(api, headers, WEBP)

    assert files_in(media_root) == {f"{first['id']}.png", f"{second['id']}.webp"}
