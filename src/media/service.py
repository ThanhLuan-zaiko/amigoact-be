"""Storing uploads and deciding who may see or attach them."""

import hashlib
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.auth.errors import api_error
from src.media import storage
from src.media.sniff import (
    MAX_UPLOAD_BYTES,
    MAX_VIDEO_BYTES,
    SNIFF_BYTES,
    detect_image,
    detect_video,
    is_video,
)
from src.models.media import MediaAsset

PUBLIC = "public"
PRIVATE = "private"
ACTIVE = "active"
ROLE_ATTACHMENT = "attachment"
NAME_LENGTH = 255
CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


def clean_filename(name: str | None) -> str | None:
    """PostgreSQL rejects NUL, so control characters are removed. The name is never used in a path."""
    if not name:
        return None
    cleaned = CONTROL_CHARACTERS.sub("", name).strip()[:NAME_LENGTH]
    return cleaned or None


def store_upload(
    db: Session,
    root: Path,
    user_id: uuid.UUID,
    data: bytes,
    original_name: str | None,
) -> MediaAsset:
    """Same file again by the same person returns the first copy.

    Someone else's copy is not shared, because its visibility belongs to them.
    """
    if not data:
        raise api_error(status.HTTP_400_BAD_REQUEST, "file_empty")
    head = data[:SNIFF_BYTES]
    kind = detect_image(head)
    limit = MAX_UPLOAD_BYTES
    if kind is None:
        kind = detect_video(head)
        limit = MAX_VIDEO_BYTES
    if kind is None:
        raise api_error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "unsupported_media_type"
        )
    if len(data) > limit:
        code = "video_too_large" if is_video(kind.mime) else "file_too_large"
        raise api_error(status.HTTP_413_CONTENT_TOO_LARGE, code)

    digest = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(MediaAsset).where(MediaAsset.file_hash == digest))
    if existing is not None and existing.uploader_id == user_id:
        return existing
    asset_id = uuid.uuid7()
    key = storage.new_storage_key(user_id, asset_id, kind.extension, datetime.now(UTC))
    storage.write_file(root, key, data)
    asset = MediaAsset(
        asset_id=asset_id,
        owner_id=user_id,
        owner_type="user",
        # Unique in the table, so another person's identical file is stored without a hash.
        file_hash=None if existing is not None else digest,
        mime=kind.mime,
        size_bytes=len(data),
        role=ROLE_ATTACHMENT,
        uploader_id=user_id,
        storage_key=key,
        backend="local",
        original_name=clean_filename(original_name),
        visibility=PRIVATE,
        upload_status=ACTIVE,
    )
    db.add(asset)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        storage.remove_file(root, key)
        raise
    return asset


def load_visible(
    db: Session, asset_id: uuid.UUID, viewer_id: uuid.UUID | None
) -> MediaAsset:
    """A private file that someone else asks for looks like it does not exist."""
    asset = db.get(MediaAsset, asset_id)
    if asset is None or asset.upload_status != ACTIVE:
        raise api_error(status.HTTP_404_NOT_FOUND, "media_not_found")
    if asset.visibility != PUBLIC and asset.uploader_id != viewer_id:
        raise api_error(status.HTTP_404_NOT_FOUND, "media_not_found")
    return asset


def _reject_video(asset: MediaAsset) -> None:
    """Logos, avatars, covers, and post images must be pictures. Only galleries take video."""
    if is_video(asset.mime):
        raise api_error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "unsupported_media_type"
        )


def check_attachable(
    db: Session, asset_id: uuid.UUID, user_id: uuid.UUID, *, allow_video: bool = False
) -> MediaAsset:
    """Only the uploader may attach a file. Attaching makes it public, as a logo or photo must be.

    The row is locked until the caller commits, so a cleanup run cannot mark it deleted
    in between. The caller must commit the reference in the same transaction.
    """
    asset = db.get(MediaAsset, asset_id, with_for_update=True)
    if asset is None or asset.upload_status != ACTIVE or asset.uploader_id != user_id:
        raise api_error(status.HTTP_404_NOT_FOUND, "media_not_found")
    if not allow_video:
        _reject_video(asset)
    asset.visibility = PUBLIC
    return asset


def stored_file(root: Path, asset: MediaAsset) -> Path:
    if asset.storage_key is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "media_not_found")
    path = storage.file_path(root, asset.storage_key)
    if not path.is_file():
        raise api_error(status.HTTP_404_NOT_FOUND, "media_not_found")
    return path


def owned_asset(db: Session, asset_id: uuid.UUID, user_id: uuid.UUID) -> MediaAsset:
    """Check ownership without changing visibility. Used while a post is still a draft.

    Locks the row like check_attachable, so the cleanup cannot remove it before the commit.
    """
    asset = db.get(MediaAsset, asset_id, with_for_update=True)
    if asset is None or asset.upload_status != ACTIVE or asset.uploader_id != user_id:
        raise api_error(status.HTTP_404_NOT_FOUND, "media_not_found")
    _reject_video(asset)
    return asset


def publish_asset(asset: MediaAsset) -> None:
    asset.visibility = PUBLIC
