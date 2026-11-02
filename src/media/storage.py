"""Files on the local disk. Names come from UUIDs only, never from the upload."""

import re
import uuid
from pathlib import Path

from src.config import get_media_settings

STORAGE_KEY = re.compile(r"[0-9a-f]{32}\.(jpg|png|webp)")


def get_media_root() -> Path:
    return get_media_settings().media_dir


def new_storage_key(extension: str) -> str:
    return f"{uuid.uuid7().hex}.{extension}"


def file_path(root: Path, key: str) -> Path:
    """Only keys we generated are accepted, so a key can never leave the root."""
    if STORAGE_KEY.fullmatch(key) is None:
        raise ValueError("invalid storage key")
    return root / key


def write_file(root: Path, key: str, data: bytes) -> None:
    root.mkdir(parents=True, exist_ok=True)
    file_path(root, key).write_bytes(data)


def remove_file(root: Path, key: str) -> None:
    file_path(root, key).unlink(missing_ok=True)
