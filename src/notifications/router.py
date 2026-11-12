"""Routes for a user's own notifications and preferences."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from src.auth.deps import CurrentPrincipal, Db
from src.auth.errors import api_error
from src.models.notifications import Notification, NotificationPreference
from src.notifications.live import queue_push
from src.notifications.schemas import (
    NotificationPage,
    NotificationResponse,
    PreferencesRequest,
    PreferencesResponse,
    UnreadCount,
)
from src.validation import Uuid7

router = APIRouter(prefix="/notifications", tags=["notifications"])

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=100_000)]
UNREAD = "unread"
READ = "read"


def _unread_count(db: Session, user_id: uuid.UUID) -> int:
    count = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.status == UNREAD)
    )
    return count or 0


@router.get("")
def list_notifications(
    principal: CurrentPrincipal,
    db: Db,
    unread_only: bool = False,
    limit: Limit = 20,
    offset: Offset = 0,
) -> NotificationPage:
    user_id = principal.user.id
    query = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        query = query.where(Notification.status == UNREAD)
    rows = db.scalars(
        query.order_by(Notification.notification_id.desc())
        .limit(limit + 1)
        .offset(offset)
    ).all()
    return NotificationPage(
        items=[
            NotificationResponse(
                id=row.notification_id,
                type=row.type,
                data=row.data_json or {},
                read=row.status == READ,
                created_at=row.created_at,
            )
            for row in rows[:limit]
        ],
        next_offset=offset + limit if len(rows) > limit else None,
        unread_count=_unread_count(db, user_id),
    )


@router.get("/unread-count")
def unread_count(principal: CurrentPrincipal, db: Db) -> UnreadCount:
    return UnreadCount(count=_unread_count(db, principal.user.id))


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
def read_all(principal: CurrentPrincipal, db: Db) -> None:
    db.execute(
        update(Notification)
        .where(
            Notification.user_id == principal.user.id,
            Notification.status == UNREAD,
        )
        .values(status=READ, read_at=datetime.now(UTC))
    )
    # The bell in the viewer's other tabs clears too.
    queue_push(db, principal.user.id, {"type": "notification.read_all"})
    db.commit()


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def read_one(notification_id: Uuid7, principal: CurrentPrincipal, db: Db) -> None:
    """Someone else's notification looks like it does not exist."""
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != principal.user.id:
        raise api_error(status.HTTP_404_NOT_FOUND, "notification_not_found")
    if notification.status == UNREAD:
        notification.status = READ
        notification.read_at = datetime.now(UTC)
        queue_push(
            db,
            principal.user.id,
            {"type": "notification.read", "id": str(notification_id)},
        )
        db.commit()


def _preferences(preference: NotificationPreference | None) -> PreferencesResponse:
    channels = preference.channels if preference else {}
    return PreferencesResponse(
        inapp=channels.get("inapp", True),
        email=channels.get("email", False),
        muted_types=preference.muted_types if preference else [],
    )


@router.get("/preferences")
def get_preferences(principal: CurrentPrincipal, db: Db) -> PreferencesResponse:
    return _preferences(db.get(NotificationPreference, principal.user.id))


@router.put("/preferences")
def set_preferences(
    payload: PreferencesRequest, principal: CurrentPrincipal, db: Db
) -> PreferencesResponse:
    user_id = principal.user.id
    preference = db.get(NotificationPreference, user_id)
    if preference is None:
        preference = NotificationPreference(user_id=user_id)
        db.add(preference)
    preference.channels = {"inapp": payload.inapp, "email": payload.email}
    preference.muted_types = sorted(set(payload.muted_types))
    db.commit()
    return _preferences(preference)
