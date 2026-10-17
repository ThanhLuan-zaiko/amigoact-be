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

    def inbox_changed(
        self,
        action: str,
        room_id: UUID,
        org_id: UUID,
        peer_ids: tuple[UUID, ...] = (),
    ) -> None:
        """Inbox hint: members:{org} for group rooms, dm peers' inboxes.

        The payload deliberately avoids an "action" key: roster and
        presence handlers on those channels key off "action"/"presence",
        so a scoped frame slips past them untouched.
        """
        if self._manager is None:
            return
        payload = {
            "scope": "chat-inbox",
            "event": action,
            "room_id": str(room_id),
            "org_id": str(org_id),
        }
        if peer_ids:
            for user_id in peer_ids:
                self._manager.schedule_publish(
                    f"notifications:{user_id}", payload
                )
        else:
            self._manager.schedule_publish(f"members:{org_id}", payload)
