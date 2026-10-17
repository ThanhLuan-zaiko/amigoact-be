"""Dataclass DTOs shared by the chat service, router, and tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class AttachmentBrief:
    """One file embedded in a message; url is the public /media/ path."""

    media_id: UUID
    url: str
    mime: str
    name: str
    size_bytes: int


@dataclass(frozen=True)
class ReactionTally:
    """Aggregated count of one emoji; `mine` marks the viewer's pick."""

    emoji: str
    count: int
    mine: bool


@dataclass(frozen=True)
class MentionBrief:
    """One @-mentioned member embedded in a message."""

    user_id: UUID
    name: str


@dataclass(frozen=True)
class ChatMessageSnapshot:
    """One message joined with its author display name."""

    message_id: UUID
    room_id: UUID
    author_id: UUID
    author_name: str
    body: str
    created_at: datetime | None
    reply_to_id: UUID | None = None
    reply_to_author: str | None = None
    reply_to_body: str | None = None
    edited_at: datetime | None = None
    attachments: tuple[AttachmentBrief, ...] = ()
    reactions: tuple[ReactionTally, ...] = ()
    mentions: tuple[MentionBrief, ...] = ()


@dataclass(frozen=True)
class ChatPage:
    """Oldest-first page plus the resume cursor and badge fields.

    peer_last_read_message_id is dm-only: it drives the sender's
    double-check receipt and stays None inside group rooms so the read
    pointers of many members are never exposed.
    """

    items: list[ChatMessageSnapshot]
    next_cursor: str | None
    unread: int
    last_read_message_id: UUID | None
    peer_last_read_message_id: UUID | None = None
    # Phase 3: the room's pinned bar (None when nothing is pinned) and
    # the caller's own mute flag for the composer/header affordance.
    pinned: "ChatMessageSnapshot | None" = None
    muted: bool = False


@dataclass(frozen=True)
class ReadSnapshot:
    last_read_message_id: UUID
    last_read_at: datetime | None


@dataclass(frozen=True)
class DmRoomSnapshot:
    """One dm inbox entry joined with the peer display name."""

    room_id: UUID
    org_id: UUID
    peer_id: UUID
    peer_name: str
    created_at: datetime | None


@dataclass(frozen=True)
class InboxRoomSnapshot:
    """One conversation row of the cross-org inbox (Telegram-style).

    kind is "general" | "activity" | "dm". title is the row label
    (org name, activity title or peer name); last_* carry the newest
    message preview or None for a room nobody wrote in yet. avatar_url
    is the org logo for group rooms, the peer avatar for dms.
    """

    room_id: UUID
    kind: str
    org_id: UUID
    org_name: str
    title: str
    peer_id: UUID | None
    last_message_id: UUID | None
    last_body: str | None
    last_author_name: str | None
    last_at: datetime | None
    unread: int
    sort_at: datetime
    avatar_url: str | None = None
    peer_last_seen_at: datetime | None = None
    muted: bool = False
