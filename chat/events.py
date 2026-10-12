"""WebSocket-backed ChatEvents implementation (best-effort publish)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from chat.interfaces import ChatEvents

if TYPE_CHECKING:
    from core.realtime import ConnectionManager


class WsChatEvents(ChatEvents):
    """Fan room changes onto chat:{room_id} subscribers (best-effort)."""

    def __init__(self, manager: ConnectionManager | None) -> None:
        self._manager = manager

    def message_changed(
        self,
        room_id: UUID,
        action: str,
        message_id: UUID,
        actor_id: UUID,
    ) -> None:
        if self._manager is None:
            return
        self._manager.schedule_publish(
            f"chat:{room_id}",
            {
                "action": action,
                "message_id": str(message_id),
                "actor_id": str(actor_id),
            },
        )
