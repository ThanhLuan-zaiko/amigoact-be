"""Request and response bodies of the notification API."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.notifications.events import NotificationType
from src.organizations.schemas import StrictRequest


class PreferencesRequest(StrictRequest):
    inapp: bool = True
    email: bool = False
    muted_types: list[NotificationType] = Field(default_factory=list)


class PreferencesResponse(BaseModel):
    inapp: bool
    email: bool
    muted_types: list[str]


class NotificationResponse(BaseModel):
    id: uuid.UUID
    type: str
    data: dict[str, Any]
    read: bool
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationResponse]
    next_offset: int | None
    unread_count: int


class UnreadCount(BaseModel):
    count: int
