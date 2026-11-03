import os
import uuid
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from src.app import app
from src.media.layout_migration import run
from tests.activity_helpers import user
from tests.conftest import ApiContext
from tests.integration.test_media_layout_migration import migrate, move_to_account_tree
from tests.media_helpers import PNG, uploaded

Bearer = Callable[[str], dict[str, str]]


def test_a_copy_that_is_not_a_hard_link_is_reported_and_kept(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, user_id = user(api, bearer, "owner")
    asset_id = uploaded(api, headers, PNG)["id"]
    _, link, _ = move_to_account_tree(media_root, user_id, asset_id)
    link.unlink()
    copy = media_root / "users" / user_id / "avatar" / f"{asset_id}.png"
    copy.write_bytes(PNG)

    report = migrate(media_root, apply=True)

    assert copy.read_bytes() == PNG
    assert [path.name for path in report.leftover_files] == [copy.name]
    assert (media_root / "users").exists()


def test_a_file_outside_the_account_tree_is_never_touched(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, _ = user(api, bearer, "owner")
    asset_id = uploaded(api, headers, PNG)["id"]
    stranger = media_root / f"{uuid.uuid4()}.png"
    stranger.write_bytes(PNG)
    past = stranger.stat().st_mtime - 86_400
    os.utime(stranger, (past, past))

    with Session(app.state.engine) as db:
        run(db, media_root, apply=True)

    assert stranger.read_bytes() == PNG
    assert (media_root / f"{asset_id}.png").read_bytes() == PNG
