import os
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.models.media import MediaAsset
from tests.activity_helpers import user
from tests.conftest import ORG_FIELDS, ApiContext
from tests.media_helpers import (
    PNG,
    age,
    clean,
    db_row,
    stored,
    unique_picture,
    uploaded,
)

Bearer = Callable[[str], dict[str, str]]


def create_with_logo(api: ApiContext, headers: dict[str, str], logo_id: str) -> Any:
    return api.client.post(
        "/organizations",
        headers=headers,
        json={**ORG_FIELDS, "name": f"CLB {api.tag}", "logo_asset_id": logo_id},
    )


def test_dry_run_lists_the_old_unused_upload_and_changes_nothing(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, user_id = user(api, bearer, "owner")
    old = uploaded(api, headers, unique_picture())
    age(old["id"], 60)

    plan = clean(media_root, user_id, apply=False)

    assert uuid.UUID(old["id"]) in plan.assets
    assert len(plan.files) == 1
    assert db_row(MediaAsset, uuid.UUID(old["id"])).upload_status == "active"
    assert len(stored(media_root, user_id, old["id"])) == 1


def test_apply_marks_the_unused_upload_deleted_and_removes_its_file(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, user_id = user(api, bearer, "owner")
    old = uploaded(api, headers, unique_picture())
    age(old["id"], 60)

    clean(media_root, user_id, apply=True)

    row = db_row(MediaAsset, uuid.UUID(old["id"]))
    assert row.upload_status == "deleted"
    assert row.deleted_at is not None
    assert row.file_hash is None
    assert stored(media_root, user_id, old["id"]) == []
    gone = api.client.get(f"/media/{old['id']}/file", headers=headers)
    assert gone.status_code == 404


def test_logo_and_recent_uploads_survive_the_cleanup(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    headers, user_id = user(api, bearer, "owner")
    logo = uploaded(api, headers, unique_picture())
    assert create_with_logo(api, headers, logo["id"]).status_code == 201
    age(logo["id"], 60)
    recent = uploaded(api, headers, unique_picture())

    clean(media_root, user_id, apply=True)

    assert db_row(MediaAsset, uuid.UUID(logo["id"])).upload_status == "active"
    assert len(stored(media_root, user_id, logo["id"])) == 1
    assert db_row(MediaAsset, uuid.UUID(recent["id"])).upload_status == "active"
    assert len(stored(media_root, user_id, recent["id"])) == 1


def test_file_without_a_row_goes_once_old_and_its_folders_go_with_it(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    _, user_id = user(api, bearer, "owner")
    folder = media_root / "users" / user_id / "by-date" / "2001" / "01" / "01"
    folder.mkdir(parents=True)
    orphan = folder / f"{uuid.uuid4()}.png"
    orphan.write_bytes(PNG)
    past = (datetime.now(UTC) - timedelta(days=60)).timestamp()
    os.utime(orphan, (past, past))

    clean(media_root, user_id, apply=True)

    assert not orphan.exists()
    assert not (media_root / "users" / user_id / "by-date" / "2001").exists()


def test_file_without_a_row_is_kept_during_the_grace_period(
    api: ApiContext, bearer: Bearer, media_root: Path
) -> None:
    # A file is written before its row is committed, so a fresh one must not be removed.
    _, user_id = user(api, bearer, "owner")
    folder = media_root / "users" / user_id / "by-date"
    folder.mkdir(parents=True)
    fresh = folder / f"{uuid.uuid4()}.png"
    fresh.write_bytes(PNG)

    clean(media_root, user_id, apply=True)

    assert fresh.exists()
