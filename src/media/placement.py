"""Folders that show whose each file is and what it is used for.

A file is stored once, under its uploader's by-date folder. Each use adds a hard
link under users/<uploader>/<folders>/, so a file used as a logo and as a gallery
item shows in both folders. Ending a use removes only its link, never the file.
Where hard links are not possible, the file is copied instead.
"""

import os
import re
import shutil
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from src.media import storage
from src.models.media import MediaAsset

FOLDER_NAME = re.compile(r"[a-z][a-z-]*|[0-9a-f-]{36}")


def target_path(root: Path, asset: MediaAsset, folders: tuple[str, ...]) -> Path:
    """Where the link of this asset goes. Folder names are checked, so none can escape."""
    for folder in folders:
        if FOLDER_NAME.fullmatch(folder) is None:
            raise ValueError("invalid folder name")
    if asset.uploader_id is None or asset.storage_key is None:
        raise ValueError("asset has no owner folder")
    extension = asset.storage_key.rsplit(".", 1)[1]
    return storage.user_dir(root, asset.uploader_id).joinpath(
        *folders, f"{asset.asset_id}.{extension}"
    )


def _asset(db: Session, asset_id: uuid.UUID | None) -> MediaAsset | None:
    if asset_id is None:
        return None
    asset = db.get(MediaAsset, asset_id)
    if asset is None or asset.uploader_id is None or asset.storage_key is None:
        return None
    return asset


def link(db: Session, root: Path, asset_id: uuid.UUID | None, *folders: str) -> None:
    """Show the file under the folders. Doing it twice changes nothing."""
    asset = _asset(db, asset_id)
    if asset is None:
        return
    source = storage.file_path(root, asset.storage_key or "")
    target = target_path(root, asset, folders)
    if not source.is_file() or target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def unlink(db: Session, root: Path, asset_id: uuid.UUID | None, *folders: str) -> None:
    """Remove the link only. The stored file stays, because other uses may need it."""
    asset = _asset(db, asset_id)
    if asset is None:
        return
    target_path(root, asset, folders).unlink(missing_ok=True)


def replace(
    db: Session,
    root: Path,
    old_id: uuid.UUID | None,
    new_id: uuid.UUID | None,
    *folders: str,
) -> None:
    """Swap one use for another, for example when a logo is changed."""
    if old_id == new_id:
        return
    unlink(db, root, old_id, *folders)
    link(db, root, new_id, *folders)
