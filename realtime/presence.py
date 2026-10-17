"""Presence fan-out: publish online state and subscribe snapshots.

Presence rides the members:{org} channel: payloads carry "presence"
(never "action") so roster-mutation clients can distinguish the two.
Best-effort like every socket event - the registry is ephemeral and
re-snapshots on every subscribe (AGENTS.md 16.5).
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from fastapi import WebSocket

from core.realtime import ConnectionManager
from realtime.service import RealtimeService

logger = logging.getLogger("amigoact.realtime")


async def fan_presence(
    manager: ConnectionManager,
    service: RealtimeService,
    user_id: UUID,
) -> None:
    """Publish a user's current online state to every org roster channel.

    The state is read from the registry after the org lookup, never taken
    from the transition that triggered the call: two racing fan-outs (a
    fast reconnect) then publish the same final state instead of landing
    out of order. Failures are logged, never raised.
    """
    try:
        org_ids = await asyncio.to_thread(service.presence_orgs_of, user_id)
    except Exception:
        logger.warning("presence org lookup failed for %s", user_id, exc_info=True)
        return
    payload = {
        "presence": "online" if manager.is_online(user_id) else "offline",
        "user_id": str(user_id),
    }
    # The transition is also the user's last-seen moment: coming online
    # or going offline both move the stamp to now.
    await asyncio.to_thread(service.mark_seen, user_id)
    for org_id in org_ids:
        await manager.publish(f"members:{org_id}", payload)


async def read_roster(service: RealtimeService, org_id: UUID) -> list[UUID]:
    """Active member ids of one org; empty when the lookup fails."""
    try:
        return await asyncio.to_thread(service.presence_member_ids, org_id)
    except Exception:
        logger.warning("presence roster lookup failed for %s", org_id, exc_info=True)
        return []


async def send_presence_snapshot(
    manager: ConnectionManager,
    websocket: WebSocket,
    channel: str,
    roster: list[UUID],
) -> None:
    """Send the online members of a pre-read roster to one socket.

    The online set is read right before the send, so every transition
    that already happened is reflected and the snapshot never overwrites
    a newer state the client received just before it.
    """
    online = manager.online_user_ids()
    await manager.send(
        websocket,
        "event.v1",
        {
            "channel": channel,
            "payload": {
                "presence": "snapshot",
                "online": [str(uid) for uid in roster if uid in online],
            },
        },
    )
