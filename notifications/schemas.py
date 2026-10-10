"""Pydantic DTOs for the notifications HTTP contract."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class NotificationItem(BaseModel):
    """One inbox row as the client renders it."""

    id: UUID
    type: str
    title: str
    body: str
    status: str
    read_at: datetime | None
    created_at: datetime


class NotificationPage(BaseModel):
    """Slice of the user feed plus the unread badge count."""

    items: list[NotificationItem]
    total: int
    unread: int


class PreferencesBody(BaseModel):
    """Partial preference update; omitted fields keep their values."""

    channels: dict[str, bool] | None = None
    muted_types: list[str] | None = None


class PreferencesResponse(BaseModel):
    channels: dict[str, bool]
    muted_types: list[str]
