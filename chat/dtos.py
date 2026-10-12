"""Dataclass DTOs shared by the chat service, router, and tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class ChatMessageSnapshot:
    """One message joined with its author display name."""

    message_id: UUID
    room_id: UUID
    author_id: UUID
    author_name: str
    body: str
    created_at: datetime | None


@dataclass(frozen=True)
class ChatPage:
    """Oldest-first page plus the resume cursor and badge fields."""

    items: list[ChatMessageSnapshot]
    next_cursor: str | None
    unread: int
    last_read_message_id: UUID | None


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
