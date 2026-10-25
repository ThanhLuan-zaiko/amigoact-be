"""cqlengine models for the notifications bounded context."""

from __future__ import annotations

import core.database  # noqa: F401  (reactor compat shim must run first)
from core.ids import uuid7
from cassandra.cqlengine import columns, models


class Notification(models.Model):
    """Full notification row; the by-user feed holds a light projection."""

    __table_name__ = "notifications"

    notification_id = columns.UUID(primary_key=True, default=uuid7)
    user_id = columns.UUID(required=True)
    type = columns.Text(required=True, default="system")
    title = columns.Text(required=True)
    body = columns.Text(required=False, default="")
    data_json = columns.Text(required=False)
    channel = columns.Text(required=True, default="inapp")
    status = columns.Text(required=True, default="unread")
    read_at = columns.DateTime(required=False)
    created_at = columns.DateTime(required=True)


class NotificationsByUser(models.Model):
    """Newest-first per-user feed; drives the bell and the inbox page."""

    __table_name__ = "notifications_by_user"

    user_id = columns.UUID(primary_key=True, partition_key=True)
    created_at = columns.DateTime(primary_key=True, clustering_order="DESC")
    notification_id = columns.UUID(
        primary_key=True, clustering_order="ASC", default=uuid7
    )
    title = columns.Text(required=True)
    status = columns.Text(required=True, default="unread")


class NotificationPreference(models.Model):
    """Per-user delivery preferences: muted types + channel toggles."""

    __table_name__ = "notification_preferences"

    user_id = columns.UUID(primary_key=True)
    channels = columns.Map(columns.Text, columns.Boolean)
    muted_types = columns.Set(columns.Text)
    updated_at = columns.DateTime()
