"""Notification events on the recipient's own topic, sent once the change is saved."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from src.models.notifications import Notification
from src.realtime import bus
from src.realtime.names import user_topic


def notification_event(notification: Notification) -> dict[str, Any]:
    """The same fields as one item of GET /notifications."""
    return {
        "type": "notification.created",
        "notification": {
            "id": str(notification.notification_id),
            "type": notification.type,
            "data": notification.data_json or {},
            "read": False,
            "created_at": notification.created_at.isoformat(),
        },
    }


def deleted_event(notification: Notification) -> dict[str, Any]:
    """Says whether it was read, so the bell knows whether to lower its count."""
    body = notification_event(notification)
    body["type"] = "notification.deleted"
    body["notification"]["read"] = notification.status == "read"
    return body


def queue_push(db: Session, user_id: uuid.UUID, body: dict[str, Any]) -> None:
    bus.emit(db, user_topic(user_id), body)
