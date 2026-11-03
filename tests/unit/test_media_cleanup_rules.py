import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.media.cleanup import (
    cutoff_for,
    empty_folders,
    file_asset_id,
    modified_at,
    should_remove,
)

NOW = datetime(2026, 11, 3, tzinfo=UTC)
CUTOFF = NOW - timedelta(days=30)
OLD = CUTOFF - timedelta(days=1)
FRESH = CUTOFF + timedelta(days=1)


def test_cutoff_is_the_grace_period_before_now() -> None:
    assert cutoff_for(NOW, 30) == NOW - timedelta(days=30)
    assert cutoff_for(NOW, 0) == NOW


@pytest.mark.parametrize(
    "name",
    [
        "0195c2e4-3f7a-7c1d-9b2e-4a5f6c7d8e9f.png",
        "0195c2e4-3f7a-7c1d-9b2e-4a5f6c7d8e9f.webm",
    ],
)
def test_stored_file_names_give_their_asset_id(name: str) -> None:
    assert file_asset_id(name) == uuid.UUID(name.split(".")[0])


@pytest.mark.parametrize(
    "name",
    [
        "notes.txt",
        "0195c2e4-3f7a-7c1d-9b2e-4a5f6c7d8e9f.exe",
        "0195c2e4-3f7a-7c1d-9b2e-4a5f6c7d8e9x.png",
        "0195c2e4-3f7a-7c1d-9b2e-4a5f6c7d8e9f.png.bak",
        "logo.png",
    ],
)
def test_other_names_are_never_candidates(name: str) -> None:
    assert file_asset_id(name) is None


def test_expired_asset_goes_even_if_its_file_is_fresh() -> None:
    asset = uuid.uuid7()

    assert should_remove(asset, FRESH, CUTOFF, expired={asset}, active={asset})


def test_active_asset_stays_even_if_its_file_is_old() -> None:
    asset = uuid.uuid7()

    assert not should_remove(asset, OLD, CUTOFF, expired=set(), active={asset})


def test_file_without_a_row_goes_only_after_the_grace_period() -> None:
    asset = uuid.uuid7()

    assert should_remove(asset, OLD, CUTOFF, expired=set(), active=set())
    assert not should_remove(asset, FRESH, CUTOFF, expired=set(), active=set())


def test_empty_folders_are_found_deepest_first(tmp_path: Path) -> None:
    base = tmp_path / "users" / "u"
    (base / "empty").mkdir(parents=True)
    (base / "nested" / "inner").mkdir(parents=True)
    (base / "doomed_dir").mkdir()
    doomed = base / "doomed_dir" / "doomed.png"
    doomed.write_bytes(b"x")
    (base / "keep").mkdir()
    (base / "keep" / "kept.png").write_bytes(b"x")

    removable = empty_folders(base, {doomed})

    assert set(removable) == {
        base / "empty",
        base / "nested" / "inner",
        base / "nested",
        base / "doomed_dir",
    }
    depths = [len(folder.parts) for folder in removable]
    assert depths == sorted(depths, reverse=True)


def test_missing_base_has_nothing_to_remove(tmp_path: Path) -> None:
    assert empty_folders(tmp_path / "missing", set()) == []


def test_modified_time_is_read_from_the_file(tmp_path: Path) -> None:
    path = tmp_path / "x.png"
    path.write_bytes(b"x")
    os.utime(path, (OLD.timestamp(), OLD.timestamp()))

    assert modified_at(path) == OLD
