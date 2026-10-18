"""HTTP layer for board-editor uploads: thin routing over PostUploads.

Editor images and videos are post-owned. They never land in the org gallery.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile, status

from core.config import Settings, get_settings
from core.dependencies import CurrentUser, get_current_user
from core.dependencies_workspace import get_post_upload_service
from core.exceptions import MediaTooLargeError
from core.media import media_kind
from posts.schemas import PostUploadResponse
from posts.uploads import PostUploads

router = APIRouter(tags=["posts"])


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    """Stream a multipart upload in 1MB chunks, capping the byte count."""
    parts: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise MediaTooLargeError("File exceeds the size limit.")
        parts.append(chunk)
    return b"".join(parts)


@router.post(
    "/orgs/{org_id}/posts/media",
    response_model=PostUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_post_media(
    org_id: UUID,
    file: UploadFile,
    current_user: CurrentUser = Depends(get_current_user),
    service: PostUploads = Depends(get_post_upload_service),
    settings: Settings = Depends(get_settings),
) -> PostUploadResponse:
    """Board editor upload: post media, never the org gallery."""
    mime = file.content_type or "application/octet-stream"
    guessed = media_kind(mime)
    max_mb = {
        "image": settings.media_max_image_mb,
        "video": settings.media_max_video_mb,
    }.get(guessed or "", max(settings.media_max_image_mb, settings.media_max_video_mb))
    content = await _read_limited(file, max_mb * 1024 * 1024)
    snap = await asyncio.to_thread(
        service.upload,
        org_id,
        current_user.id,
        file.filename or "upload",
        mime,
        content,
    )
    return PostUploadResponse(
        id=snap.id,
        org_id=snap.org_id,
        kind=snap.kind,
        mime=snap.mime,
        size_bytes=snap.size_bytes,
        file_url=snap.file_url,
        original_name=snap.original_name,
    )
