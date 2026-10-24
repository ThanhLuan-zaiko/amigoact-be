"""HTTP layer for the cross-org chat inbox (Telegram-style list).

Split from router.py for the 350-line rule; same thin-routing style.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from chat.inbox_service import ChatInboxService
from chat.schemas import ChatInboxResponse, InboxRoomResponse
from core.dependencies import CurrentUser, get_current_user
from core.dependencies_chat import get_chat_inbox_service

router = APIRouter(tags=["chat"])


@router.get("/chat/inbox", response_model=ChatInboxResponse)
def list_inbox(
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatInboxService = Depends(get_chat_inbox_service),
) -> ChatInboxResponse:
    """Every room the caller can open across orgs, freshest first."""
    return ChatInboxResponse(
        items=[
            InboxRoomResponse(
                room_id=item.room_id,
                kind=item.kind,
                org_id=item.org_id,
                org_name=item.org_name,
                title=item.title,
                org_slug=item.org_slug,
                peer_id=item.peer_id,
                avatar_url=item.avatar_url,
                last_message_id=item.last_message_id,
                last_body=item.last_body,
                last_author_name=item.last_author_name,
                last_at=item.last_at,
                unread=item.unread,
                sort_at=item.sort_at,
                peer_last_seen_at=item.peer_last_seen_at,
                muted=item.muted,
                post_policy=item.post_policy,
                channel_kind=item.channel_kind,
                parent_room_id=item.parent_room_id,
                activity_id=item.activity_id,
                activity_deleted=item.activity_deleted,
            )
            for item in service.list_inbox(current_user.id)
        ]
    )
