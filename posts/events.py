"""WebSocket-backed PostEvents implementation (best-effort publish)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from posts.interfaces import PostEvents

if TYPE_CHECKING:
    from core.realtime import ConnectionManager


class WsPostEvents(PostEvents):
    """Fan board changes onto posts:{org_id} subscribers (best-effort)."""

    def __init__(self, manager: ConnectionManager | None) -> None:
        self._manager = manager

    def feed_changed(
        self,
        org_id: UUID,
        action: str,
        post_id: UUID,
        actor_id: UUID,
        detail: str | None = None,
    ) -> None:
        if self._manager is None:
            return
        payload: dict[str, str] = {
            "action": action,
            "post_id": str(post_id),
            "actor_id": str(actor_id),
        }
        if detail is not None:
            payload["detail"] = detail
        self._manager.schedule_publish(f"posts:{org_id}", payload)
