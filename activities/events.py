"""WebSocket-backed ActivityEvents implementation (best-effort publish)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from activities.interfaces import ActivityEvents

if TYPE_CHECKING:
    from core.realtime import ConnectionManager


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
