"""Public events:feed fan-out shared by activities and registrations.

Payloads carry ids and an action only. Guests may subscribe, so no actor,
student or organizer identity ever enters this channel. Subscribers
refetch the browse feed on a hint; the payload is never trusted as data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from core.realtime import ConnectionManager

EVENTS_FEED_CHANNEL = "events:feed"


def publish_events_feed(
    manager: ConnectionManager | None,
    action: str,
    activity_id: UUID,
    org_id: UUID,
) -> None:
    """Best-effort hint; a missing registry never fails the request."""
    if manager is None:
        return
    manager.schedule_publish(
        EVENTS_FEED_CHANNEL,
        {
            "action": action,
            "activity_id": str(activity_id),
            "org_id": str(org_id),
        },
    )
