import uuid
from collections.abc import Callable
from pathlib import Path

from tests.activity_helpers import make_org, user
from tests.conftest import ApiContext
from tests.media_helpers import PNG, placed, set_avatar, stored, uploaded

Bearer = Callable[[str], dict[str, str]]


def test_someone_elses_file_gets_no_link_in_their_tree(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner_headers, owner_id = user(api, bearer, "file-owner")
    intruder_headers, intruder_id = user(api, bearer, "intruder")
    foreign = uploaded(api, owner_headers, PNG)

    response = set_avatar(api, intruder_headers, foreign["id"])

    assert response.status_code == 404
    assert placed(media_root, intruder_id, "avatar") == set()
    assert placed(media_root, owner_id, "avatar") == set()


def test_one_file_used_twice_is_stored_once_and_linked_in_both_places(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, user_id = user(api, bearer, "double-use")
    slug = make_org(api, headers)
    asset = uploaded(api, headers, PNG)
    api.client.put(
        f"/organizations/{slug}/logo", headers=headers, json={"asset_id": asset["id"]}
    )
    api.client.post(
        f"/organizations/{slug}/gallery",
        headers=headers,
        json={"asset_id": asset["id"]},
    )

    assert len(stored(media_root, user_id, asset["id"])) == 1
    assert set_avatar(api, headers, asset["id"]).status_code == 204
    assert placed(media_root, user_id, "avatar") == {f"{asset['id']}.png"}
    assert len(stored(media_root, user_id, asset["id"])) == 1


def test_removing_the_avatar_keeps_the_stored_file(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, user_id = user(api, bearer, "clear-avatar")
    asset = uploaded(api, headers, PNG)
    set_avatar(api, headers, asset["id"])

    cleared = set_avatar(api, headers, None)

    assert cleared.status_code == 204
    assert placed(media_root, user_id, "avatar") == set()
    assert len(stored(media_root, user_id, asset["id"])) == 1


def test_link_names_never_come_from_the_upload(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, user_id = user(api, bearer, "named")
    asset = uploaded(api, headers, PNG)
    set_avatar(api, headers, asset["id"])

    names = placed(media_root, user_id, "avatar")

    assert names == {f"{uuid.UUID(asset['id'])}.png"}
