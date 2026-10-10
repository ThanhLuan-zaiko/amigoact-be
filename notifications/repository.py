"""cqlengine persistence for notifications (dual-table writes)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from notifications.interfaces import (
    NotificationStore,
    PreferenceStore,
)
from notifications.model import (
    Notification,
    NotificationPreference,
    NotificationsByUser,
)


class CqlNotificationStore(NotificationStore):
    """Writes the canonical row plus the per-user feed projection."""

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
        row = Notification.create(
            notification_id=notification_id,
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            data_json=data_json,
            channel="inapp",
            status="unread",
            created_at=now,
        )
        NotificationsByUser.create(
            user_id=user_id,
            created_at=now,
            notification_id=notification_id,
            title=title,
            status="unread",
        )
        return row

    def get(self, notification_id: UUID) -> Notification | None:
        return Notification.objects(notification_id=notification_id).first()

    def list_by_user(self, user_id: UUID) -> list[NotificationsByUser]:
        return list(NotificationsByUser.objects(user_id=user_id).all())

    def mark_read(self, row: Notification, now: datetime) -> None:
        Notification.objects(notification_id=row.notification_id).update(
            status="read", read_at=now
        )
        NotificationsByUser.objects(
            user_id=row.user_id,
            created_at=row.created_at,
            notification_id=row.notification_id,
        ).update(status="read")


class CqlPreferenceStore(PreferenceStore):
    """Single-row-per-user preferences; absent row means defaults."""

    def get(self, user_id: UUID) -> NotificationPreference | None:
        try:
            return NotificationPreference.get(user_id=user_id)
        except NotificationPreference.DoesNotExist:
            return None

    def save(
        self,
        user_id: UUID,
        channels: dict[str, bool],
        muted_types: set[str],
        now: datetime,
    ) -> NotificationPreference:
        NotificationPreference.objects(user_id=user_id).update(
            channels=channels, muted_types=muted_types, updated_at=now
        )
        row = self.get(user_id)
        assert row is not None
        return row
