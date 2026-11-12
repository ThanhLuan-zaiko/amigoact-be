"""Routes for uploading an image and reading it back."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import FileResponse

from src.auth.deps import CurrentPrincipal, Db, OptionalPrincipal
from src.auth.rate_limit import enforce_rate_limit
from src.chat.attachments import can_view
from src.media import service
from src.media.schemas import MediaResponse
from src.media.sniff import MAX_VIDEO_BYTES
from src.media.storage import get_media_root
from src.validation import Uuid7

router = APIRouter(tags=["media"])

UPLOAD_LIMIT = 60
UPLOAD_WINDOW = 60 * 60
PUBLIC_CACHE = "public, max-age=86400"
PRIVATE_CACHE = "private, max-age=3600"
MediaRoot = Annotated[Path, Depends(get_media_root)]


@router.post("/media", status_code=status.HTTP_201_CREATED)
def upload_media(
    file: Annotated[UploadFile, File()],
    principal: CurrentPrincipal,
    db: Db,
    root: MediaRoot,
) -> MediaResponse:
    enforce_rate_limit(
        db, f"media-upload:{principal.user.id}", UPLOAD_LIMIT, UPLOAD_WINDOW
    )
    # One byte more than the largest limit is enough to tell a too large file apart.
    data = file.file.read(MAX_VIDEO_BYTES + 1)
    asset = service.store_upload(db, root, principal.user.id, data, file.filename)
    return MediaResponse.from_asset(asset)


@router.get("/media/{asset_id}/file")
def get_media_file(
    asset_id: Uuid7,
    principal: OptionalPrincipal,
    db: Db,
    root: MediaRoot,
) -> FileResponse:
    viewer_id = principal.user.id if principal else None
    asset = service.load_visible(
        db, asset_id, viewer_id, lambda item: can_view(db, item, viewer_id)
    )
    path = service.stored_file(root, asset)
    cache = PUBLIC_CACHE if asset.visibility == service.PUBLIC else PRIVATE_CACHE
    return FileResponse(
        path,
        media_type=asset.mime,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": cache},
    )
