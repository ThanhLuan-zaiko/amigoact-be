"""Files on the local disk. Every file sits flat in the media root, named by its asset id.

Layout:
  <media_root>/<asset_id>.<ext>

A file is stored once. Who uses it is recorded in the database by the foreign keys that
point at its asset (see usage.py), so the folder layout never has to say anything about
owners or uses. Names come from UUIDs only, never from the upload.
"""

import re
import uuid
from pathlib import Path

from src.config import get_media_settings

STORAGE_KEY = re.compile(r"[0-9a-f-]{36}\.(jpg|png|webp|mp4|webm)")


def get_media_root() -> Path:
    return get_media_settings().media_dir


def new_storage_key(asset_id: uuid.UUID, extension: str) -> str:
    return f"{asset_id}.{extension}"


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
