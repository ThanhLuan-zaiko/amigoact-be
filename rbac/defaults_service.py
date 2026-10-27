"""Per-org baseline permissions every active member holds."""

from __future__ import annotations

from uuid import UUID

from core.exceptions import (
    ForbiddenError,
    InvalidRoleError,
    NotFoundError,
    OrgDeletedError,
)
from orgs.interfaces import MemberEvents, MemberRepository, OrgRepository
from rbac.catalog import BASELINE_PERMISSIONS
from rbac.interfaces import AccessControl, MemberDefaultsRepository
from rbac.role_events import RoleFanOut

# Org sizes stay small, but a single edit must never fan out unbounded.
NOTIFY_LIMIT = 500


class MemberDefaultsService:
    """Owner-only editor for the baseline; any member may read it."""

    def __init__(
        self,
        orgs: OrgRepository,
        members: MemberRepository,
        defaults: MemberDefaultsRepository,
        access: AccessControl,
        events: MemberEvents | None = None,
    ) -> None:
        self._orgs = orgs
        self._members = members
        self._defaults = defaults
        self._access = access
        self._events = events
        self._fan = RoleFanOut(events)

    def _live_org(self, org_id: UUID):  # noqa: ANN202
        org = self._orgs.get_by_id(org_id)
        if org is None:
            raise NotFoundError("Organization not found.")
        if getattr(org, "deleted_at", None) is not None:
            raise OrgDeletedError("Organization is soft-deleted.")
        return org

    def get(self, org_id: UUID, viewer_id: UUID) -> list[str]:
        """Baseline codes; owner or an active member only."""
        org = self._live_org(org_id)
        row = self._members.get(org_id, viewer_id)
        active = row is not None and (row.status or "active") == "active"
        if org.owner_id != viewer_id and not active:
            raise ForbiddenError("Only org members can view this.")
        return sorted(self._defaults.list_defaults(org_id))

    def set(
        self, org_id: UUID, actor_id: UUID, permissions: list[str]
    ) -> list[str]:
        """Replace the baseline (empty clears it); owner only."""
        org = self._live_org(org_id)
        if org.owner_id != actor_id:
            self._access.record(
                org_id, actor_id, "role.defaults", "role", None, "denied"
            )
            raise ForbiddenError("Only the owner can change this.")
        codes = set(permissions)
        if not codes <= BASELINE_PERMISSIONS:
            raise InvalidRoleError("Permissions are not valid defaults.")
        self._defaults.set_defaults(org_id, codes)
        self._access.record(
            org_id, actor_id, "role.defaults", "role", None, "allowed"
        )
        self._fan.catalog(org_id, actor_id, actor_id, detail="defaults")
        active = {
            row.user_id
            for row in self._members.list_by_org(org_id)
            if (row.status or "active") == "active"
        }
        self._fan.notify(
            org_id, set(list(active)[:NOTIFY_LIMIT]), actor_id, "defaults"
        )
        return sorted(codes)
