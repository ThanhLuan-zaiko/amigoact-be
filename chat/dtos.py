"""Dataclass DTOs shared by the chat service, router, and tests."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    author_avatar_url: str | None = None
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
    # Pinned bar: every pinned message, oldest pin first; plus the
    # caller's own mute flag for the composer/header affordance.
    pinned: list[ChatMessageSnapshot] = field(default_factory=list)
    muted: bool = False


@dataclass(frozen=True)
class SharedItemDraft:
    """One attachment/link to index under a room's media tab partition."""

    kind: str  # 'image' | 'video' | 'file' | 'link'
    item_index: int
    url: str  # /media/ path; links carry ciphertext ('v1gcm:' prefix)
    media_id: UUID | None = None
    mime: str = ""
    name: str = ""
    size_bytes: int = 0


@dataclass(frozen=True)
class SharedItemSnapshot:
    """One indexed item joined with its author for the media tabs."""

    message_id: UUID
    kind: str
    media_id: UUID | None
    url: str  # plaintext: link rows are decrypted at read time
    mime: str
    name: str
    size_bytes: int
    author_id: UUID
    author_name: str
    author_avatar_url: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class SharedMediaPage:
    """Newest-first page of one media tab plus its resume cursor."""

    items: list[SharedItemSnapshot]
    next_cursor: str | None


@dataclass(frozen=True)
class SharedAuthorSnapshot:
    """One sender offered by the media filter, with the kinds shared."""

    author_id: UUID
    author_name: str
    author_avatar_url: str | None
    kinds: tuple[str, ...]
    last_at: datetime | None


@dataclass(frozen=True)
class ReadSnapshot:
    last_read_message_id: UUID
    last_read_at: datetime | None


@dataclass(frozen=True)
class RoomReadSnapshot:
    """One member's read pointer joined with their display brief.

    Powers the sender's "seen by" receipt; listing is members-only so
    the pointers never leave the room's audience.
    """

    user_id: UUID
    user_name: str
    avatar_url: str | None
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
    # Channel rows only (None elsewhere): post gate + display label.
    post_policy: str | None = None
    channel_kind: str | None = None
    # Sub-thread rows only: the room the thread hangs under and the
    # activity it was opened for (display link).
    parent_room_id: UUID | None = None
    activity_id: UUID | None = None
    # Public /orgs/{slug} path for the room panel's share-link card.
    org_slug: str = ""


@dataclass(frozen=True)
class ChannelSnapshot:
    """One named channel projected for API output.

    parent_room_id set means the row is a sub-thread of that room;
    activity_id/activity_title carry the optional linked activity.
    """

    channel_id: UUID
    org_id: UUID
    name: str
    topic: str
    kind: str
    post_policy: str
    visibility: str
    created_by: UUID
    created_at: datetime | None
    archived_at: datetime | None = None
    parent_room_id: UUID | None = None
    activity_id: UUID | None = None
    activity_title: str | None = None


@dataclass(frozen=True)
class ChannelMemberSnapshot:
    """One restricted-channel seat joined with the member brief."""

    user_id: UUID
    full_name: str
    added_at: datetime | None
    avatar_url: str | None = None
