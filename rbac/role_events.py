"""Realtime fan-out for role changes (best-effort, never raises)."""

from __future__ import annotations

from uuid import UUID

from orgs.interfaces import MemberEvents


class RoleFanOut:
    """Publishes role catalog changes on the roster and holders' inboxes."""

    def __init__(self, events: MemberEvents | None) -> None:
        self._events = events

    def catalog(
        self,
        org_id: UUID,
        role_id: UUID,
        actor_id: UUID,
        detail: str | None = None,
    ) -> None:
        """Roster refresh so every open members page reloads roles."""
        if self._events is None:
            return
        try:
            self._events.member_changed(
                org_id, "role_catalog_changed", role_id, actor_id,
                detail=detail,
            )
        except Exception:  # noqa: BLE001 - realtime is best-effort
            pass

    def notify(
        self,
        org_id: UUID,
        users: set[UUID],
        actor_id: UUID,
        detail: str,
    ) -> None:
        """Tell affected users their effective permissions moved.

        Only members:{org} subscribers hear the roster event, so someone
        browsing elsewhere would keep stale permission-gated UI.
        """
        if self._events is None:
            return
        for user_id in users - {actor_id}:
            try:
                self._events.inbox_changed(
                    user_id, "role_catalog_changed", org_id, detail=detail
                )
            except Exception:  # noqa: BLE001 - realtime is best-effort
                pass
