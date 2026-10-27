"""HTTP layer for org chat: thin routing over ChatService.

Rooms are addressed as /chat/rooms/{room_id}. The legacy
/orgs/{org_id}/chat/* aliases stay for the general room, whose id is the
org id itself.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from chat.schemas import (
    AttachmentResponse,
    ChatMessageResponse,
    ChatPageResponse,
    DmRoomListResponse,
    DmRoomResponse,
    MarkReadRequest,
    MentionResponse,
    OpenDmRequest,
    ReactionResponse,
    ReadStateResponse,
    RoomReadEntryResponse,
    RoomReadsResponse,
    SendMessageRequest,
    UnreadResponse,
)
from chat.service import ChatService
from core.config import Settings, get_settings
from core.dependencies import CurrentUser, get_current_user
from core.dependencies_chat import get_chat_service
from core.exceptions import TooManyRequestsError

logger = logging.getLogger("amigoact.chat")

router = APIRouter(tags=["chat"])


def _to_message(snapshot) -> ChatMessageResponse:  # noqa: ANN001, ANN202
    return ChatMessageResponse(
        message_id=snapshot.message_id,
        room_id=snapshot.room_id,
        author_id=snapshot.author_id,
        author_name=snapshot.author_name,
        author_avatar_url=snapshot.author_avatar_url,
        body=snapshot.body,
        created_at=snapshot.created_at,
        reply_to_id=snapshot.reply_to_id,
        reply_to_author=snapshot.reply_to_author,
        reply_to_body=snapshot.reply_to_body,
        edited_at=snapshot.edited_at,
        attachments=[
            AttachmentResponse(
                media_id=item.media_id,
                url=item.url,
                mime=item.mime,
                name=item.name,
                size_bytes=item.size_bytes,
            )
            for item in snapshot.attachments
        ],
        reactions=[
            ReactionResponse(
                emoji=item.emoji, count=item.count, mine=item.mine
            )
            for item in snapshot.reactions
        ],
        mentions=[
            MentionResponse(user_id=item.user_id, name=item.name)
            for item in snapshot.mentions
        ],
    )


def _page(room_id: UUID, viewer_id: UUID, service: ChatService,
          limit: int, cursor: str | None) -> ChatPageResponse:
    page = service.list_messages(
        room_id, viewer_id, limit=limit, cursor=cursor
    )
    return ChatPageResponse(
        items=[_to_message(item) for item in page.items],
        next_cursor=page.next_cursor,
        unread=page.unread,
        last_read_message_id=page.last_read_message_id,
        peer_last_read_message_id=page.peer_last_read_message_id,
        pinned=[_to_message(msg) for msg in page.pinned],
        muted=page.muted,
    )


def _send(
    room_id: UUID,
    user_id: UUID,
    body: SendMessageRequest,
    service: ChatService,
    settings: Settings,
) -> ChatMessageResponse:
    try:
        from auth.repository import CqlRateLimiter

        hits = CqlRateLimiter(settings.scylla_keyspace).hit(
            f"chat_send:{user_id}", 60
        )
        if hits > 60:
            raise TooManyRequestsError("Too many requests.")
    except TooManyRequestsError:
        raise
    except Exception as exc:
        logger.warning("chat rate-limit unavailable: %s", exc)
    return _to_message(
        service.send_message(
            room_id,
            user_id,
            body.body,
            reply_to_id=body.reply_to_id,
            attachment_ids=body.attachment_ids,
        )
    )


def _to_room(snapshot) -> DmRoomResponse:  # noqa: ANN001, ANN202
    return DmRoomResponse(
        room_id=snapshot.room_id,
        org_id=snapshot.org_id,
        peer_id=snapshot.peer_id,
        peer_name=snapshot.peer_name,
        created_at=snapshot.created_at,
    )


# --- Room-scoped endpoints -------------------------------------------------
# (The /chat/inbox list lives in inbox_router.py; the media index tabs in
# media_router.py - this module keeps the message resource itself.)


@router.get("/chat/rooms/{room_id}/messages", response_model=ChatPageResponse)
def list_room_messages(
    room_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
    limit: int = Query(30, ge=1, le=100),
    cursor: str | None = Query(None, max_length=80),
) -> ChatPageResponse:
    """Newest history page (oldest-first items) plus unread badge."""
    return _page(room_id, current_user.id, service, limit, cursor)


@router.get("/chat/rooms/{room_id}/unread", response_model=UnreadResponse)
def room_unread_count(
    room_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> UnreadResponse:
    """Badge-only read: same unread math, one-row history scan."""
    return UnreadResponse(
        unread=service.list_messages(room_id, current_user.id, limit=1).unread
    )


@router.post(
    "/chat/rooms/{room_id}/messages",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def send_room_message(
    room_id: UUID,
    body: SendMessageRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
    settings: Settings = Depends(get_settings),
) -> ChatMessageResponse:
    """Append one message and fan it out on chat:{room_id}."""
    return _send(room_id, current_user.id, body, service, settings)


@router.delete(
    "/chat/rooms/{room_id}/messages/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def delete_room_message(
    room_id: UUID,
    message_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> Response:
    """Author removes their message; chat:moderate holders remove any."""
    service.delete_message(room_id, current_user.id, message_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/chat/rooms/{room_id}/read", response_model=ReadStateResponse)
def mark_room_read(
    room_id: UUID,
    body: MarkReadRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> ReadStateResponse:
    """Move the caller's read pointer forward to one message."""
    snapshot = service.mark_read(room_id, current_user.id, body.message_id)
    return ReadStateResponse(
        last_read_message_id=snapshot.last_read_message_id,
        last_read_at=snapshot.last_read_at,
    )


@router.get(
    "/chat/rooms/{room_id}/reads", response_model=RoomReadsResponse
)
def room_reads(
    room_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> RoomReadsResponse:
    """Member read pointers of the room: the sender's 'seen by' list."""
    return RoomReadsResponse(
        items=[
            RoomReadEntryResponse(
                user_id=item.user_id,
                user_name=item.user_name,
                avatar_url=item.avatar_url,
                last_read_message_id=item.last_read_message_id,
                last_read_at=item.last_read_at,
            )
            for item in service.list_read_states(
                room_id, current_user.id
            )
        ]
    )


# --- Direct-message rooms ---------------------------------------------------


@router.post(
    "/orgs/{org_id}/chat/dm",
    response_model=DmRoomResponse,
    status_code=status.HTTP_201_CREATED,
)
def open_dm(
    org_id: UUID,
    body: OpenDmRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> DmRoomResponse:
    """Find or create the dm room between the caller and one peer."""
    return _to_room(service.open_dm(org_id, current_user.id, body.peer_id))


@router.get("/orgs/{org_id}/chat/dm", response_model=DmRoomListResponse)
def list_dm_rooms(
    org_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> DmRoomListResponse:
    """The caller's dm rooms inside one org."""
    return DmRoomListResponse(
        items=[
            _to_room(item)
            for item in service.list_dm_rooms(org_id, current_user.id)
        ]
    )


# --- Legacy org-wide aliases (general room = org id) ------------------------


@router.get("/orgs/{org_id}/chat/messages", response_model=ChatPageResponse)
def list_messages(
    org_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
    limit: int = Query(30, ge=1, le=100),
    cursor: str | None = Query(None, max_length=80),
) -> ChatPageResponse:
    """General room history page (kept for backward compatibility)."""
    return _page(org_id, current_user.id, service, limit, cursor)


@router.get("/orgs/{org_id}/chat/unread", response_model=UnreadResponse)
def unread_count(
    org_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> UnreadResponse:
    """General room badge-only read."""
    return UnreadResponse(
        unread=service.list_messages(org_id, current_user.id, limit=1).unread
    )


@router.post(
    "/orgs/{org_id}/chat/messages",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def send_message(
    org_id: UUID,
    body: SendMessageRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
    settings: Settings = Depends(get_settings),
) -> ChatMessageResponse:
    """Append one message to the general room."""
    return _send(org_id, current_user.id, body, service, settings)


@router.delete(
    "/orgs/{org_id}/chat/messages/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def delete_message(
    org_id: UUID,
    message_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> Response:
    """Remove one message from the general room."""
    service.delete_message(org_id, current_user.id, message_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/orgs/{org_id}/chat/read", response_model=ReadStateResponse)
def mark_read(
    org_id: UUID,
    body: MarkReadRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> ReadStateResponse:
    """Move the caller's general-room read pointer forward."""
    snapshot = service.mark_read(org_id, current_user.id, body.message_id)
    return ReadStateResponse(
        last_read_message_id=snapshot.last_read_message_id,
        last_read_at=snapshot.last_read_at,
    )
