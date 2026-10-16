"""HTTP layer for the per-activity photo/video gallery."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Response, UploadFile, status

from activities.schemas import (
    ActivityMediaItemResponse,
    ActivityMediaPatchBody,
)
from core.dependencies import (
    CurrentUser,
    get_current_user,
    get_optional_user,
)
from core.dependencies_workspace import get_activity_media_service
from core.media import media_kind
from core.config import Settings, get_settings

if TYPE_CHECKING:
    from activities.media_service import ActivityMediaItem, ActivityMediaService

router = APIRouter(tags=["activities"])


def _item(item: ActivityMediaItem) -> ActivityMediaItemResponse:
    return ActivityMediaItemResponse(
        asset_id=item.asset_id,
        position=item.position,
        role=item.role,
        caption=item.caption,
        file_url=item.file_url,
        mime=item.mime,
        kind=item.kind,
        size_bytes=item.size_bytes,
        original_name=item.original_name,
    )


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
            from core.exceptions import MediaTooLargeError

            raise MediaTooLargeError("File exceeds the size limit.")
        parts.append(chunk)
    return b"".join(parts)


@router.get(
    "/activities/{activity_id}/media",
    response_model=list[ActivityMediaItemResponse],
)
async def list_activity_media(
    activity_id: UUID,
    current: CurrentUser | None = Depends(get_optional_user),
    service: ActivityMediaService = Depends(get_activity_media_service),
) -> list[ActivityMediaItemResponse]:
    """Public gallery for the activity detail page."""
    items = service.list_media(
        activity_id, current.id if current else None
    )
    return [_item(i) for i in items]


@router.post(
    "/activities/{activity_id}/media",
    response_model=ActivityMediaItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_activity_media(
    activity_id: UUID,
    file: UploadFile,
    caption: Annotated[str | None, Form()] = None,
    role: Annotated[str, Form()] = "gallery",
    current: CurrentUser = Depends(get_current_user),
    service: ActivityMediaService = Depends(get_activity_media_service),
    settings: Settings = Depends(get_settings),
) -> ActivityMediaItemResponse:
    """Manager uploads one image/video/document to the gallery."""
    import asyncio

    guessed = media_kind(file.content_type or "application/octet-stream")
    max_mb = {
        "image": settings.media_max_image_mb,
        "video": settings.media_max_video_mb,
    }.get(
        guessed or "",
        max(settings.media_max_image_mb, settings.media_max_video_mb),
    )
    content = await _read_limited(file, max_mb * 1024 * 1024)
    item = await asyncio.to_thread(
        service.upload,
        activity_id,
        current.id,
        file.filename or "upload",
        file.content_type or "application/octet-stream",
        content,
        caption,
        role,
    )
    return _item(item)


@router.patch(
    "/activities/{activity_id}/media/{asset_id}",
    response_model=ActivityMediaItemResponse,
)
async def update_activity_media(
    activity_id: UUID,
    asset_id: UUID,
    body: ActivityMediaPatchBody,
    current: CurrentUser = Depends(get_current_user),
    service: ActivityMediaService = Depends(get_activity_media_service),
) -> ActivityMediaItemResponse:
    """Manager edits caption/role of one gallery entry."""
    item = service.update_entry(
        activity_id, current.id, asset_id, body.caption, body.role
    )
    return _item(item)


@router.delete(
    "/activities/{activity_id}/media/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_activity_media(
    activity_id: UUID,
    asset_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: ActivityMediaService = Depends(get_activity_media_service),
) -> Response:
    """Manager removes one gallery entry and its file."""
    service.delete(activity_id, current.id, asset_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
