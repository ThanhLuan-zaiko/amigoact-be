"""Request and response bodies of the media API."""

import uuid
from datetime import datetime

from pydantic import BaseModel

from src.models.media import MediaAsset
from src.organizations.schemas import StrictRequest
from src.validation import Uuid7


class MediaResponse(BaseModel):
    id: uuid.UUID
    # Relative to the API, so the frontend adds its own origin.
    url: str
    mime: str
    size_bytes: int
    visibility: str
    created_at: datetime

    @classmethod
    def from_asset(cls, asset: MediaAsset) -> MediaResponse:
        return cls(
            id=asset.asset_id,
            url=f"/media/{asset.asset_id}/file",
            mime=asset.mime or "application/octet-stream",
            size_bytes=asset.size_bytes or 0,
            visibility=asset.visibility,
            created_at=asset.created_at,
        )


class AttachRequest(StrictRequest):
    # Null removes the current picture.
    asset_id: Uuid7 | None
