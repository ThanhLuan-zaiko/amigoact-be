"""Pydantic DTOs for org chat (validation lives here)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


def _trim(value: str) -> str:
    return value.strip()


class SendMessageRequest(BaseModel):
    body: str = Field(default="", max_length=2000)
    reply_to_id: UUID | None = None
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=4)

    _body = field_validator("body", mode="before")(_trim)  # noqa: SLF001


class EditMessageRequest(BaseModel):
    body: str = Field(min_length=1, max_length=2000)

    _body = field_validator("body", mode="before")(_trim)  # noqa: SLF001


class MarkReadRequest(BaseModel):
    message_id: UUID


class PinRequest(BaseModel):
    message_id: UUID


class ReactionRequest(BaseModel):
    """Toggle one emoji from the fixed reaction palette."""

    emoji: str = Field(min_length=1, max_length=8)


class ReactionResponse(BaseModel):
    emoji: str
    count: int
    mine: bool = False


class MentionResponse(BaseModel):
    user_id: UUID
    name: str


class AttachmentResponse(BaseModel):
    """One stored chat file; url is the public /media/ path."""

    media_id: UUID
    url: str
    mime: str
    name: str
    size_bytes: int


class ChatMessageResponse(BaseModel):
    message_id: UUID
    room_id: UUID
    author_id: UUID
    author_name: str
    body: str
    created_at: datetime | None = None
    reply_to_id: UUID | None = None
    reply_to_author: str | None = None
    reply_to_body: str | None = None
    edited_at: datetime | None = None
    attachments: list[AttachmentResponse] = []
    reactions: list[ReactionResponse] = []
    mentions: list[MentionResponse] = []


class ChatPageResponse(BaseModel):
    """Oldest-first page; next_cursor resumes the bucket walk.

    peer_last_read_message_id is dm-only: the peer's read pointer for
    the sender's double-check receipt.
    """

    items: list[ChatMessageResponse]
    next_cursor: str | None = None
    unread: int = 0
    last_read_message_id: UUID | None = None
    peer_last_read_message_id: UUID | None = None
    # Phase 3: pinned bar payload (same shape as a message) + mute flag.
    pinned: ChatMessageResponse | None = None
    muted: bool = False


class ReadStateResponse(BaseModel):
    last_read_message_id: UUID
    last_read_at: datetime | None = None


class UnreadResponse(BaseModel):
    unread: int = 0


class OpenDmRequest(BaseModel):
    peer_id: UUID


class DmRoomResponse(BaseModel):
    room_id: UUID
    org_id: UUID
    peer_id: UUID
    peer_name: str
    created_at: datetime | None = None


class DmRoomListResponse(BaseModel):
    items: list[DmRoomResponse]


class InboxRoomResponse(BaseModel):
    """One inbox row: room identity plus last-message preview."""

    room_id: UUID
    kind: str  # "general" | "activity" | "dm"
    org_id: UUID
    org_name: str
    title: str
    peer_id: UUID | None = None
    avatar_url: str | None = None
    last_message_id: UUID | None = None
    last_body: str | None = None
    last_author_name: str | None = None
    last_at: datetime | None = None
    unread: int = 0
    sort_at: datetime | None = None
    peer_last_seen_at: datetime | None = None
    muted: bool = False


class ChatInboxResponse(BaseModel):
    items: list[InboxRoomResponse]
