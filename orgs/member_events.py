"""WebSocket-backed MemberEvents implementation (best-effort publish)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from core.realtime import ConnectionManager


class WsMemberEvents:
    """Fan roster and invite events onto the socket registry (best-effort)."""

    def __init__(self, manager: ConnectionManager | None) -> None:
        self._manager = manager

    def member_changed(
        self,
        org_id: UUID,
        action: str,
        target_id: UUID,
        actor_id: UUID,
        detail: str | None = None,
    ) -> None:
        if self._manager is None:
            return
        payload: dict[str, str] = {
            "action": action,
            "user_id": str(target_id),
            "actor_id": str(actor_id),
        }
        if detail is not None:
            payload["detail"] = detail
        self._manager.schedule_publish(f"members:{org_id}", payload)

    def inbox_changed(
        self,
        user_id: UUID,
        action: str,
        org_id: UUID,
        detail: str | None = None,
    ) -> None:
        if self._manager is None:
            return
        payload = {
            "scope": "membership",
            "action": action,
            "org_id": str(org_id),
        }
        if detail is not None:
            payload["detail"] = detail
        self._manager.schedule_publish(
            f"notifications:{user_id}", payload
        )
