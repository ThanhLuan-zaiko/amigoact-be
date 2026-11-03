import re
import uuid
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from src.app import app
from src.media.backfill import run
from src.models.media import MediaAsset
from tests.activity_helpers import user
from tests.conftest import ApiContext
from tests.media_helpers import PNG, db_row, placed, set_avatar, uploaded

Bearer = Callable[[str], dict[str, str]]


def test_flat_file_moves_into_the_tree_and_regains_its_link(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, user_id = user(api, bearer, "legacy-user")
    body = uploaded(api, headers, PNG)
    asset_id = uuid.UUID(body["id"])
    set_avatar(api, headers, body["id"])
    # Rebuild the state from before the tree: a flat file and no avatar link.
    flat_key = uuid.uuid4().hex + ".png"
    row = db_row(MediaAsset, asset_id)
    (media_root / row.storage_key).rename(media_root / flat_key)
    (media_root / "users" / user_id / "avatar" / f"{asset_id}.png").unlink()
    with Session(app.state.engine) as session:
        asset = session.get(MediaAsset, asset_id)
        assert asset is not None
        asset.storage_key = flat_key
        session.commit()

    with Session(app.state.engine) as session:
        report = run(session, media_root, apply=True)

    moved = db_row(MediaAsset, asset_id)
    pattern = rf"users/{user_id}/by-date/\d{{4}}/\d{{2}}/\d{{2}}/{asset_id}\.png"
    assert re.fullmatch(pattern, moved.storage_key)
    assert (media_root / moved.storage_key).read_bytes() == PNG
    assert not (media_root / flat_key).exists()
    assert placed(media_root, user_id, "avatar") == {f"{asset_id}.png"}
    assert report.moved >= 1
    assert report.linked >= 1


def test_dry_run_reports_and_changes_nothing(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, _ = user(api, bearer, "dry-run-user")
    body = uploaded(api, headers, PNG)
    asset_id = uuid.UUID(body["id"])
    flat_key = uuid.uuid4().hex + ".png"
    row = db_row(MediaAsset, asset_id)
    (media_root / row.storage_key).rename(media_root / flat_key)
    with Session(app.state.engine) as session:
        asset = session.get(MediaAsset, asset_id)
        assert asset is not None
        asset.storage_key = flat_key
        session.commit()

    with Session(app.state.engine) as session:
        report = run(session, media_root, apply=False)

    assert report.moved >= 1
    assert db_row(MediaAsset, asset_id).storage_key == flat_key
    assert (media_root / flat_key).is_file()
