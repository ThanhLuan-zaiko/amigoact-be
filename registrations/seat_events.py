"""WebSocket-backed SeatEvents: best-effort public hint on events:feed."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from core.events_feed import publish_events_feed
from registrations.interfaces import SeatEvents

if TYPE_CHECKING:
    from core.realtime import ConnectionManager


class WsSeatEvents(SeatEvents):
    """Tells public browse readers that a seat count may have moved."""

    def __init__(self, manager: ConnectionManager | None) -> None:
        self._manager = manager

    def seats_changed(self, activity_id: UUID, org_id: UUID) -> None:
        publish_events_feed(self._manager, "seats", activity_id, org_id)
