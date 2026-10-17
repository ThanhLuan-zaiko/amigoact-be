"""HTTP layer for chat writes added in phase 1: edit + attachment upload.

Split from router.py for the 350-line rule; same thin-routing style.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, Response, UploadFile, status

from chat.router import _to_message
from chat.schemas import (
    AttachmentResponse,
    ChatMessageResponse,
    EditMessageRequest,
    PinRequest,
    ReactionRequest,
)
from chat.service import ChatService
from core.config import Settings, get_settings
from core.dependencies import CurrentUser, get_current_user
from core.dependencies_workspace import get_chat_service
from core.exceptions import MediaTooLargeError
from core.media import media_kind

router = APIRouter(tags=["chat"])


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


@router.patch(
    "/chat/rooms/{room_id}/messages/{message_id}",
    response_model=ChatMessageResponse,
)
def edit_room_message(
    room_id: UUID,
    message_id: UUID,
    body: EditMessageRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> ChatMessageResponse:
    """Author rewrites their message text; fans out message.edited."""
    return _to_message(
        service.edit_message(room_id, current_user.id, message_id, body.body)
    )


@router.put(
    "/chat/rooms/{room_id}/messages/{message_id}/reactions",
    response_model=ChatMessageResponse,
)
def toggle_reaction(
    room_id: UUID,
    message_id: UUID,
    body: ReactionRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> ChatMessageResponse:
    """Toggle one palette emoji; returns the message with tallies."""
    return _to_message(
        service.toggle_reaction(
            room_id, current_user.id, message_id, body.emoji
        )
    )


@router.put("/chat/rooms/{room_id}/pin", status_code=204,
            response_class=Response, response_model=None)
def pin_message(
    room_id: UUID,
    body: PinRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> Response:
    """Managers pin one message; the slot holds only the latest pin."""
    service.pin_message(room_id, current_user.id, body.message_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/chat/rooms/{room_id}/pin", status_code=204,
               response_class=Response, response_model=None)
def unpin_message(
    room_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> Response:
    """Managers clear the room's pinned slot."""
    service.unpin_message(room_id, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/chat/rooms/{room_id}/mute", status_code=204,
            response_class=Response, response_model=None)
def mute_room(
    room_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> Response:
    """Mute the room for the caller (per-user, no broadcast)."""
    service.set_mute(room_id, current_user.id, True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/chat/rooms/{room_id}/mute", status_code=204,
               response_class=Response, response_model=None)
def unmute_room(
    room_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> Response:
    """Remove the caller's mute flag."""
    service.set_mute(room_id, current_user.id, False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/chat/rooms/{room_id}/attachments",
    response_model=AttachmentResponse,
    status_code=201,
)
async def upload_room_attachment(
    room_id: UUID,
    file: UploadFile,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
    settings: Settings = Depends(get_settings),
) -> AttachmentResponse:
    """Stage one image/video as a message attachment.

    The returned media_id is echoed back in SendMessageRequest; the org
    media pipeline keeps validation, normalization and storage.
    """
    mime = file.content_type or "application/octet-stream"
    guessed = media_kind(mime)
    max_mb = {
        "image": settings.media_max_image_mb,
        "video": settings.media_max_video_mb,
    }.get(guessed or "", max(settings.media_max_image_mb, settings.media_max_video_mb))
    content = await _read_limited(file, max_mb * 1024 * 1024)
    snap = await asyncio.to_thread(
        service.create_attachment,
        room_id,
        current_user.id,
        file.filename or "upload",
        mime,
        content,
    )
    return AttachmentResponse(
        media_id=snap.media_id,
        url=snap.url,
        mime=snap.mime,
        name=snap.name,
        size_bytes=snap.size_bytes,
    )
