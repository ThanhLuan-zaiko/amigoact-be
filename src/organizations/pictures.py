"""Logo and cover of an organization: attaching an upload and building its URL."""

import uuid

from sqlalchemy.orm import Session

from src.media import service as media_service


def picture_url(media_id: uuid.UUID | None) -> str | None:
    """Relative path, so the frontend can serve the picture from its own origin."""
    return f"/media/{media_id}/file" if media_id is not None else None


def attach_picture(
    db: Session, asset_id: uuid.UUID | None, user_id: uuid.UUID
) -> uuid.UUID | None:
    """Only the uploader may attach a picture. A missing or foreign asset is a 404."""
    if asset_id is None:
        return None
    return media_service.check_attachable(db, asset_id, user_id).asset_id
