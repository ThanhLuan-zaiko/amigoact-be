"""WS adapter: fans public directory changes onto orgs:directory."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from orgs.interfaces import OrgDirectoryEvents

if TYPE_CHECKING:
    from core.realtime import ConnectionManager


class WsOrgDirectoryEvents(OrgDirectoryEvents):
    """Publish visibility events; payload stays public-only (id plus slug)."""

    def __init__(self, manager: ConnectionManager | None) -> None:
        self._manager = manager

    def directory_changed(self, action: str, org_id: UUID, slug: str) -> None:
        """Fire-and-forget fan-out; a dead registry never breaks a request."""
        if self._manager is not None:
            self._manager.schedule_publish(
                "orgs:directory",
                {"action": action, "org_id": str(org_id), "slug": slug},
            )
