"""Abstract ports for the notifications bounded context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from notifications.model import (
    Notification,
    NotificationPreference,
    NotificationsByUser,
)


class NotificationPort(ABC):
    """Cross-feature write port: other contexts emit notifications only."""

    @abstractmethod
    def notify(
        self,
        user_id: UUID,
        type: str,
        title: str,
        body: str = "",
        data_json: str | None = None,
    ) -> None:
        """Persist one in-app notification for a user (best-effort callers)."""


class NotificationPublisher(ABC):
    """Realtime fan-out port: push new-notification pings over the socket."""

    @abstractmethod
    def push(self, user_id: UUID, payload: dict) -> None:
        """Publish a lightweight ping on notifications:{user_id}."""


class NotificationStore(ABC):
    """Persistence port for the notification table plus the user feed."""

    @abstractmethod
    def create(
        self,
        notification_id: UUID,
        user_id: UUID,
        type: str,
        title: str,
        body: str,
        data_json: str | None,
        now: datetime,
    ) -> Notification:
        """Insert the full row and the denormalized feed entry."""

    @abstractmethod
    def get(self, notification_id: UUID) -> Notification | None:
        """Load one notification by primary key."""

    @abstractmethod
    def list_by_user(self, user_id: UUID) -> list[NotificationsByUser]:
        """Newest-first feed rows for one user."""

    @abstractmethod
    def mark_read(self, row: Notification, now: datetime) -> None:
        """Stamp read_at and flip status on both tables."""


class PreferenceStore(ABC):
    """Persistence port for per-user notification preferences."""

    @abstractmethod
    def get(self, user_id: UUID) -> NotificationPreference | None:
        """Load the user's preferences row, or None for defaults."""

    @abstractmethod
    def save(
        self,
        user_id: UUID,
        channels: dict[str, bool],
        muted_types: set[str],
        now: datetime,
    ) -> NotificationPreference:
        """Replace the preferences row (upsert by primary key)."""
