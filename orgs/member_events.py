"""WebSocket-backed MemberEvents implementation (best-effort publish)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from core.realtime import ConnectionManager

# Roster exits that end a user's access to the org-scoped channels.
REVOKING_ACTIONS = frozenset({"suspended", "removed", "left"})


async def revoke_channels(
    manager: ConnectionManager, user_id: UUID, channels: Sequence[str]
) -> int:
    """Drop channels from every socket of a user who lost access.

    Subscriptions are authorized once at join time, so without this an
    open socket would keep receiving roster and presence events after a
    suspension or removal. Each client gets unsubscribed.v1 with reason
    ACCESS_REVOKED so it stops re-joining on reconnect.
    """
    dropped = 0
    for websocket in manager.sockets_of(user_id):
        for channel in channels:
            if not manager.unsubscribe(websocket, channel):
                continue
            dropped += 1
            try:
                await manager.send(
                    websocket,
                    "unsubscribed.v1",
                    {"channel": channel, "reason": "ACCESS_REVOKED"},
                )
            except Exception:
                continue
    return dropped


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
        if action in REVOKING_ACTIONS:
            # Scheduled after the publish, which snapshots its socket list
            # first: the target still receives the explaining roster event.
            self._manager.schedule(
                revoke_channels(
                    self._manager,
                    target_id,
                    (
                        f"members:{org_id}",
                        f"activities:{org_id}",
                        f"posts:{org_id}",
                        f"chat:{org_id}",
                    ),
                )
            )

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
