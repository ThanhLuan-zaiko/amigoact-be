import uuid
from pathlib import Path

import pytest

from src.media.placement import target_path
from src.models.media import MediaAsset


def asset(storage_key: str | None = "users/x/by-date/2026/11/03/y.png") -> MediaAsset:
    return MediaAsset(
        asset_id=uuid.uuid7(),
        uploader_id=uuid.uuid7(),
        storage_key=storage_key,
    )


def test_target_sits_under_the_uploaders_folder_named_by_asset(tmp_path: Path) -> None:
    item = asset()
    org_id = str(uuid.uuid7())

    target = target_path(tmp_path, item, ("organizations", org_id, "logo"))

    expected = (
        tmp_path
        / "users"
        / str(item.uploader_id)
        / "organizations"
        / org_id
        / "logo"
        / f"{item.asset_id}.png"
    )
    assert target == expected


@pytest.mark.parametrize("folder", ["..", "../x", "a/b", "Logo", "", "x y", "org-1"])
def test_folder_names_that_could_leave_the_tree_are_refused(
    tmp_path: Path, folder: str
) -> None:
    with pytest.raises(ValueError):
        target_path(tmp_path, asset(), (folder,))


def test_an_asset_without_owner_or_file_has_no_place_in_the_tree(
    tmp_path: Path,
) -> None:
    orphan = MediaAsset(asset_id=uuid.uuid7(), uploader_id=None, storage_key="x")
    with pytest.raises(ValueError):
        target_path(tmp_path, orphan, ("avatar",))
    with pytest.raises(ValueError):
        target_path(tmp_path, asset(storage_key=None), ("avatar",))
