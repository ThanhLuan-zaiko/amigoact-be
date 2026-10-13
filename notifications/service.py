"""Notification business rules: emit, list, mark read. No FastAPI here."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from core.exceptions import ForbiddenError, NotFoundError
from core.ids import uuid7
from core.security import utcnow
from notifications.interfaces import (
    NotificationPort,
    NotificationPublisher,
    NotificationStore,
    PreferenceStore,
)


@dataclass(frozen=True)
class NotificationSnapshot:
    """Feed row joined with its full body for the response."""

    id: UUID
    type: str
    title: str
    body: str
    status: str
    read_at: datetime | None
    created_at: datetime
    data: dict[str, Any] | None = None


@dataclass(frozen=True)
class PreferencesView:
    """Effective preferences; defaults when the row is absent."""

    channels: dict[str, bool]
    muted_types: set[str]


class NotificationService(NotificationPort):
    """Implements NotificationPort so other contexts can emit; also reads."""

    def __init__(
        self,
        store: NotificationStore,
        publisher: NotificationPublisher | None = None,
        prefs: PreferenceStore | None = None,
    ) -> None:
        self._store = store
        self._publisher = publisher
        self._prefs = prefs

    def _muted(self, user_id: UUID, type: str) -> bool:
        if self._prefs is None:
            return False
        row = self._prefs.get(user_id)
        if row is not None and type in (row.muted_types or set()):
            return True
        if row is not None and row.channels is not None:
            return row.channels.get("inapp", True) is False
        return False

    def get_preferences(self, user_id: UUID) -> PreferencesView:
        """Effective preferences; defaults when nothing is stored."""
        if self._prefs is None:
            return PreferencesView(
                channels={"inapp": True}, muted_types=set()
            )
        row = self._prefs.get(user_id)
        if row is None:
            return PreferencesView(
                channels={"inapp": True}, muted_types=set()
            )
        return PreferencesView(
            channels=dict(row.channels or {"inapp": True}),
            muted_types=set(row.muted_types or set()),
        )

    def update_preferences(
        self,
        user_id: UUID,
        channels: dict[str, bool] | None,
        muted_types: set[str] | None,
    ) -> PreferencesView:
        """Merge a partial update over the stored row, then persist."""
        if self._prefs is None:
            raise NotFoundError("Preferences unavailable.")
        current = self.get_preferences(user_id)
        next_channels = (
            current.channels
            if channels is None
            else {**current.channels, **dict(channels)}
        )
        next_muted = (
            current.muted_types
            if muted_types is None
            else set(muted_types)
        )
        self._prefs.save(
            user_id, next_channels, next_muted, utcnow()
        )
        return PreferencesView(
            channels=next_channels, muted_types=next_muted
        )

    def notify(
        self,
        user_id: UUID,
        type: str,
        title: str,
        body: str = "",
        data_json: str | None = None,
    ) -> None:
        """Persist one notification; callers treat delivery as best-effort."""
        if self._muted(user_id, type):
            return
        self._store.create(
            uuid7(), user_id, type, title, body, data_json, utcnow()
        )
        if self._publisher is not None:
            try:
                self._publisher.push(
                    user_id, {"scope": "inapp", "type": type, "title": title}
                )
            except Exception:  # noqa: BLE001 - realtime is best-effort
                pass

    @staticmethod
    def _data(raw: str | None) -> dict[str, Any] | None:
        """Deep-link payload stored beside the row; corrupt data never
        breaks the inbox."""
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def list_mine(
        self, user_id: UUID, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[NotificationSnapshot], int, int]:
        """Slice the feed; returns (items, total, unread_count)."""
        feed = self._store.list_by_user(user_id)
        unread = sum(1 for row in feed if (row.status or "unread") == "unread")
        items: list[NotificationSnapshot] = []
        for row in feed[offset : offset + limit]:
            full = self._store.get(row.notification_id)
            items.append(
                NotificationSnapshot(
                    id=row.notification_id,
                    type=full.type if full is not None else "system",
                    title=row.title,
                    body=full.body if full is not None else "",
                    status=row.status or "unread",
                    read_at=full.read_at if full is not None else None,
                    created_at=row.created_at,
                    data=self._data(
                        full.data_json if full is not None else None
                    ),
                )
            )
        return items, len(feed), unread

    def mark_read(
        self, user_id: UUID, notification_id: UUID
    ) -> NotificationSnapshot:
        """Owner flips one notification to read."""
        row = self._store.get(notification_id)
        if row is None:
            raise NotFoundError("Notification not found.")
        if row.user_id != user_id:
            raise ForbiddenError("Not your notification.")
        if row.status != "read":
            self._store.mark_read(row, utcnow())
        fresh = self._store.get(notification_id)
        assert fresh is not None
        return NotificationSnapshot(
            id=fresh.notification_id,
            type=fresh.type,
            title=fresh.title,
            body=fresh.body or "",
            status="read",
            read_at=fresh.read_at,
            created_at=fresh.created_at,
            data=self._data(fresh.data_json),
        )

    def mark_all_read(self, user_id: UUID) -> int:
        """Owner clears the whole unread badge in one sweep."""
        return self._store.mark_all_read(user_id, utcnow())
