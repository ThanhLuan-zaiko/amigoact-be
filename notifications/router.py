"""HTTP layer for notifications: parsing and status codes only."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from core.dependencies import (
    CurrentUser,
    get_current_user,
    get_notification_service,
)
from notifications.schemas import (
    NotificationItem,
    NotificationPage,
    PreferencesBody,
    PreferencesResponse,
)

if TYPE_CHECKING:
    from notifications.service import NotificationService, NotificationSnapshot

router = APIRouter(tags=["notifications"])


def _prefs(view: object) -> PreferencesResponse:
    return PreferencesResponse(
        channels=dict(view.channels),
        muted_types=sorted(view.muted_types),
    )


@router.get(
    "/notifications/preferences",
    response_model=PreferencesResponse,
)
def get_preferences(
    current: CurrentUser = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> PreferencesResponse:
    """Effective delivery preferences (defaults when unset)."""
    return _prefs(service.get_preferences(current.id))


@router.put(
    "/notifications/preferences",
    response_model=PreferencesResponse,
)
def update_preferences(
    body: PreferencesBody,
    current: CurrentUser = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> PreferencesResponse:
    """Merge a partial update into the user's preferences."""
    return _prefs(
        service.update_preferences(
            current.id,
            body.channels,
            set(body.muted_types) if body.muted_types is not None else None,
        )
    )


def _item(snapshot: NotificationSnapshot) -> NotificationItem:
    return NotificationItem(
        id=snapshot.id,
        type=snapshot.type,
        title=snapshot.title,
        body=snapshot.body,
        status=snapshot.status,
        read_at=snapshot.read_at,
        created_at=snapshot.created_at,
    )


@router.get("/notifications", response_model=NotificationPage)
def list_notifications(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current: CurrentUser = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationPage:
    """Newest-first inbox slice plus the unread badge count."""
    items, total, unread = service.list_mine(
        current.id, limit=limit, offset=offset
    )
    return NotificationPage(
        items=[_item(item) for item in items], total=total, unread=unread
    )


@router.post(
    "/notifications/{notification_id}/read", response_model=NotificationItem
)
def mark_notification_read(
    notification_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationItem:
    """Owner marks one notification as read."""
    return _item(service.mark_read(current.id, notification_id))
