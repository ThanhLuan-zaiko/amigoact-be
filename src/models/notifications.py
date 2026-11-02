"""Notification tables: the inbox and each user's delivery choices."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models import auth  # noqa: F401  registers users for the foreign keys
from src.models.base import Base


class Notification(Base):
    __tablename__ = "notifications"

    notification_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid7
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    # A stable code. The frontend turns it and data_json into Vietnamese text.
    type: Mapped[str]
    data_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    channel: Mapped[str] = mapped_column(server_default="inapp")
    status: Mapped[str] = mapped_column(server_default="unread")
    read_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    channels: Mapped[dict[str, bool]] = mapped_column(JSONB, server_default="{}")
    muted_types: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    # Kept current by the set_updated_at trigger, not by the ORM.
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
