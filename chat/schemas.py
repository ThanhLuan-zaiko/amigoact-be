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
    author_avatar_url: str | None = None
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


class SharedMediaItemResponse(BaseModel):
    """One indexed attachment/link joined with its author."""

    message_id: UUID
    kind: str  # "image" | "video" | "file" | "link"
    media_id: UUID | None = None
    url: str
    mime: str = ""
    name: str = ""
    size_bytes: int = 0
    author_id: UUID
    author_name: str
    author_avatar_url: str | None = None
    created_at: datetime | None = None


class SharedMediaPageResponse(BaseModel):
    """Newest-first page of one media tab plus its resume cursor."""

    items: list[SharedMediaItemResponse]
    next_cursor: str | None = None


class SharedMediaAuthorResponse(BaseModel):
    """One sender offered by the media tabs' author filter."""

    author_id: UUID
    author_name: str
    author_avatar_url: str | None = None
    kinds: list[str]
    last_at: datetime | None = None


class SharedMediaAuthorsResponse(BaseModel):
    items: list[SharedMediaAuthorResponse]


class InboxRoomResponse(BaseModel):
    """One inbox row: room identity plus last-message preview."""

    room_id: UUID
    kind: str  # "general" | "activity" | "dm" | "channel"
    org_id: UUID
    org_name: str
    title: str
    org_slug: str = ""
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
    # Channel rows only: composer gate + display label.
    post_policy: str | None = None
    channel_kind: str | None = None


class ChatInboxResponse(BaseModel):
    items: list[InboxRoomResponse]


class ChannelResponse(BaseModel):
    """One named channel of an org."""

    channel_id: UUID
    org_id: UUID
    name: str
    topic: str = ""
    kind: str  # "text" | "report" | "task"
    post_policy: str  # "everyone" | "managers"
    visibility: str  # "org" | "restricted"
    created_by: UUID
    created_at: datetime | None = None
    archived_at: datetime | None = None


class ChannelListResponse(BaseModel):
    items: list[ChannelResponse]


class ChannelCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    topic: str = Field(default="", max_length=200)
    kind: str = Field(default="text", pattern="^(text|report|task)$")
    post_policy: str = Field(
        default="everyone", pattern="^(everyone|managers)$"
    )
    visibility: str = Field(default="org", pattern="^(org|restricted)$")
    member_ids: list[UUID] = Field(default_factory=list, max_length=200)

    _name = field_validator("name", mode="before")(_trim)  # noqa: SLF001


class ChannelUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    topic: str | None = Field(default=None, max_length=200)
    kind: str | None = Field(default=None, pattern="^(text|report|task)$")
    post_policy: str | None = Field(
        default=None, pattern="^(everyone|managers)$"
    )
    visibility: str | None = Field(
        default=None, pattern="^(org|restricted)$"
    )
    archived: bool | None = None

    _name = field_validator("name", mode="before")(_trim)  # noqa: SLF001


class ChannelMemberResponse(BaseModel):
    """One restricted-channel seat joined with the member brief."""

    user_id: UUID
    full_name: str
    avatar_url: str | None = None
    added_at: datetime | None = None


class ChannelMemberListResponse(BaseModel):
    items: list[ChannelMemberResponse]


class ChannelMemberAddRequest(BaseModel):
    user_id: UUID
