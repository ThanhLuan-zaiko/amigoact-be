"""HTTP layer for the room media index (info-panel tabs).

Split from router.py for the 350-line rule; same thin-routing style.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from chat.media_service import ChatMediaService
from chat.schemas import (
    SharedMediaAuthorResponse,
    SharedMediaAuthorsResponse,
    SharedMediaItemResponse,
    SharedMediaPageResponse,
)
from core.dependencies import CurrentUser, get_current_user
from core.dependencies_chat import get_chat_media_service

router = APIRouter(tags=["chat"])


@router.get(
    "/chat/rooms/{room_id}/media",
    response_model=SharedMediaPageResponse,
)
def list_shared_media(
    room_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatMediaService = Depends(get_chat_media_service),
    kind: str = Query("image", pattern="^(image|video|file|link)$"),
    limit: int = Query(30, ge=1, le=60),
    cursor: str | None = Query(None, max_length=80),
    author_id: UUID | None = Query(None),
) -> SharedMediaPageResponse:
    """Newest page of one shared-media tab for the room info panel.

    `author_id` narrows the listing to one sender (org_room_media_by_
    author partition); the cursor contract is unchanged.
    """
    page = service.list_shared_media(
        room_id,
        current_user.id,
        kind=kind,
        limit=limit,
        cursor=cursor,
        author_id=author_id,
    )
    return SharedMediaPageResponse(
        items=[
            SharedMediaItemResponse(
                message_id=item.message_id,
                kind=item.kind,
                media_id=item.media_id,
                url=item.url,
                mime=item.mime,
                name=item.name,
                size_bytes=item.size_bytes,
                author_id=item.author_id,
                author_name=item.author_name,
                author_avatar_url=item.author_avatar_url,
                created_at=item.created_at,
            )
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )


@router.get(
    "/chat/rooms/{room_id}/media/authors",
    response_model=SharedMediaAuthorsResponse,
)
def list_shared_media_authors(
    room_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatMediaService = Depends(get_chat_media_service),
) -> SharedMediaAuthorsResponse:
    """Senders with at least one indexed item - the filter's options."""
    return SharedMediaAuthorsResponse(
        items=[
            SharedMediaAuthorResponse(
                author_id=author.author_id,
                author_name=author.author_name,
                author_avatar_url=author.author_avatar_url,
                kinds=list(author.kinds),
                last_at=author.last_at,
            )
            for author in service.list_media_authors(
                room_id, current_user.id
            )
        ]
    )
