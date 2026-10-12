"""Pydantic DTOs for org chat (validation lives here)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


def _trim(value: str) -> str:
    return value.strip()


class SendMessageRequest(BaseModel):
    body: str = Field(min_length=1, max_length=2000)

    _body = field_validator("body", mode="before")(_trim)  # noqa: SLF001


class MarkReadRequest(BaseModel):
    message_id: UUID


class ChatMessageResponse(BaseModel):
    message_id: UUID
    room_id: UUID
    author_id: UUID
    author_name: str
    body: str
    created_at: datetime | None = None


class ChatPageResponse(BaseModel):
    """Oldest-first page; next_cursor resumes the bucket walk."""

    items: list[ChatMessageResponse]
    next_cursor: str | None = None
    unread: int = 0
    last_read_message_id: UUID | None = None


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
