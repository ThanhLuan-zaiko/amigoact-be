import os
import uuid
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from src.app import app
from src.media.layout_migration import Report, run
from src.models.media import MediaAsset
from tests.activity_helpers import user
from tests.conftest import ApiContext
from tests.media_helpers import PNG, db_row, uploaded

Bearer = Callable[[str], dict[str, str]]


def move_to_account_tree(
    media_root: Path, user_id: str, asset_id: str
) -> tuple[Path, Path, str]:
    """Put a flat file back where the old layout kept it, with one hard link beside it."""
    legacy_key = f"users/{user_id}/by-date/2001/01/01/{asset_id}.png"
    legacy = media_root / legacy_key
    legacy.parent.mkdir(parents=True)
    os.replace(media_root / f"{asset_id}.png", legacy)
    link = media_root / "users" / user_id / "avatar" / f"{asset_id}.png"
    link.parent.mkdir(parents=True)
    os.link(legacy, link)
    with Session(app.state.engine) as session:
        row = session.get(MediaAsset, uuid.UUID(asset_id))
        assert row is not None
        row.storage_key = legacy_key
        session.commit()
    return legacy, link, legacy_key


def migrate(media_root: Path, *, apply: bool) -> Report:
    with Session(app.state.engine) as db:
        return run(db, media_root, apply=apply)


def test_dry_run_reports_the_move_and_changes_nothing(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, user_id = user(api, bearer, "owner")
    asset_id = uploaded(api, headers, PNG)["id"]
    legacy, link, legacy_key = move_to_account_tree(media_root, user_id, asset_id)

    report = migrate(media_root, apply=False)

    assert report.moved == 1
    assert report.links_removed == 1
    assert legacy.is_file() and link.is_file()
    assert db_row(MediaAsset, uuid.UUID(asset_id)).storage_key == legacy_key


def test_apply_moves_the_file_and_removes_the_old_links(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, user_id = user(api, bearer, "owner")
    asset_id = uploaded(api, headers, PNG)["id"]
    move_to_account_tree(media_root, user_id, asset_id)

    report = migrate(media_root, apply=True)

    assert report.moved == 1
    assert report.links_removed == 1
    assert (media_root / f"{asset_id}.png").read_bytes() == PNG
    assert db_row(MediaAsset, uuid.UUID(asset_id)).storage_key == f"{asset_id}.png"
    assert not (media_root / "users").exists()
    response = api.client.get(f"/media/{asset_id}/file", headers=headers)
    assert response.status_code == 200
    assert response.content == PNG


def test_a_name_already_taken_is_reported_and_the_row_is_kept(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, user_id = user(api, bearer, "owner")
    asset_id = uploaded(api, headers, PNG)["id"]
    legacy, _, legacy_key = move_to_account_tree(media_root, user_id, asset_id)
    (media_root / f"{asset_id}.png").write_bytes(b"another file")

    report = migrate(media_root, apply=True)

    assert report.conflicts == 1
    assert report.moved == 0
    assert legacy.read_bytes() == PNG
    assert db_row(MediaAsset, uuid.UUID(asset_id)).storage_key == legacy_key
