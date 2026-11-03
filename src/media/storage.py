"""Files on the local disk. Names come from UUIDs only, never from the upload.

Layout:
  users/<uploader_id>/by-date/<yyyy>/<mm>/<dd>/<asset_id>.<ext>  the stored file
  users/<uploader_id>/<folders...>/<asset_id>.<ext>             one hard link per use

Files stored before this layout stay flat as <hex>.<ext>. They keep working.
"""

import re
import uuid
from datetime import datetime
from pathlib import Path

from src.config import get_media_settings

STORAGE_KEY = re.compile(
    r"(users/[0-9a-f-]{36}/by-date/[0-9]{4}/[0-9]{2}/[0-9]{2}/[0-9a-f-]{36}|[0-9a-f]{32})"
    r"\.(jpg|png|webp|mp4|webm)"
)


def get_media_root() -> Path:
    return get_media_settings().media_dir


def new_storage_key(
    owner_id: uuid.UUID, asset_id: uuid.UUID, extension: str, when: datetime
) -> str:
    return f"users/{owner_id}/by-date/{when:%Y/%m/%d}/{asset_id}.{extension}"


def user_dir(root: Path, user_id: uuid.UUID) -> Path:
    return root / "users" / str(user_id)


def file_path(root: Path, key: str) -> Path:
    """Only keys we generated are accepted, so a key can never leave the root."""
    if STORAGE_KEY.fullmatch(key) is None:
        raise ValueError("invalid storage key")
    return root / key


def write_file(root: Path, key: str, data: bytes) -> None:
    path = file_path(root, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def remove_file(root: Path, key: str) -> None:
    file_path(root, key).unlink(missing_ok=True)
