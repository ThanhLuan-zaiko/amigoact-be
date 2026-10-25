"""WebSocket-backed ActivityEvents implementation (best-effort publish)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from activities.interfaces import ActivityEvents
from core.events_feed import publish_events_feed

if TYPE_CHECKING:
    from core.realtime import ConnectionManager

# Statuses the public browse feed serves; drafts never reach events:feed.
_PUBLIC_STATUSES = frozenset({"published", "ongoing", "completed"})
_REMOVED_ACTIONS = frozenset({"deleted", "cancelled"})


class WsActivityEvents(ActivityEvents):
    """Fan lifecycle changes onto activities:{org_id} subscribers."""

    def __init__(self, manager: ConnectionManager | None) -> None:
        self._manager = manager

    def activity_changed(
        self,
        org_id: UUID,
        action: str,
        activity_id: UUID,
        actor_id: UUID,
        status: str,
    ) -> None:
        if self._manager is None:
            return
        self._manager.schedule_publish(
            f"activities:{org_id}",
            {
                "action": action,
                "activity_id": str(activity_id),
                "actor_id": str(actor_id),
                "status": status,
            },
        )
        self._publish_public(org_id, action, activity_id, status)

    def _publish_public(
        self, org_id: UUID, action: str, activity_id: UUID, status: str
    ) -> None:
        """Mirror only changes a public browse card can show."""
        if action in _REMOVED_ACTIONS:
            publish_events_feed(self._manager, "removed", activity_id, org_id)
        elif status in _PUBLIC_STATUSES and not action.startswith("slot_"):
            publish_events_feed(self._manager, "updated", activity_id, org_id)

    def tags_changed(
        self, org_id: UUID, action: str, slug: str, actor_id: UUID
    ) -> None:
        if self._manager is None:
            return
        payload = {
            "action": f"tag.{action}",
            "slug": slug,
            "actor_id": str(actor_id),
        }
        self._manager.schedule_publish(f"activities:{org_id}", payload)
        # Board readers treat this as a refetch hint. Unknown actions
        # invalidate the post cache and do not raise a toast.
        self._manager.schedule_publish(f"posts:{org_id}", payload)
