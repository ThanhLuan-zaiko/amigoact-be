from collections.abc import Callable
from pathlib import Path

from tests.activity_helpers import user
from tests.conftest import ApiContext
from tests.media_helpers import PNG, set_avatar, uploaded

Bearer = Callable[[str], dict[str, str]]


def test_someone_elses_file_cannot_be_attached_and_nothing_is_written(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    owner_headers, _ = user(api, bearer, "file-owner")
    intruder_headers, _ = user(api, bearer, "intruder")
    foreign = uploaded(api, owner_headers, PNG)
    before = {entry.name for entry in media_root.iterdir()}

    response = set_avatar(api, intruder_headers, foreign["id"])

    assert response.status_code == 404
    assert {entry.name for entry in media_root.iterdir()} == before
    assert (media_root / f"{foreign['id']}.png").read_bytes() == PNG
