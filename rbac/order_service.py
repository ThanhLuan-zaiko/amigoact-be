"""Org-wide role seniority: the owner ranks custom roles top to bottom."""

from __future__ import annotations

from uuid import UUID

from core.exceptions import (
    ForbiddenError,
    InvalidRoleError,
    NotFoundError,
    OrgDeletedError,
)
from orgs.interfaces import MemberEvents, OrgRepository
from rbac.interfaces import AccessControl, RoleRepository
from rbac.role_events import RoleFanOut


class RoleOrderService:
    """Rewrites roles.position so seniority follows the submitted order."""

    def __init__(
        self,
        orgs: OrgRepository,
        roles: RoleRepository,
        access: AccessControl,
        events: MemberEvents | None = None,
    ) -> None:
        self._orgs = orgs
        self._roles = roles
        self._access = access
        self._fan = RoleFanOut(events)

    def reorder(
        self, org_id: UUID, actor_id: UUID, ordered_ids: list[UUID]
    ) -> None:
        """Most senior first; the list must name every custom role once."""
        org = self._orgs.get_by_id(org_id)
        if org is None:
            raise NotFoundError("Organization not found.")
        if getattr(org, "deleted_at", None) is not None:
            raise OrgDeletedError("Organization is soft-deleted.")
        if org.owner_id != actor_id:
            self._access.record(
                org_id, actor_id, "role.reorder", "role", None, "denied"
            )
            raise ForbiddenError("Only the owner can reorder roles.")
        customs = {row.id for row in self._roles.list_org_roles(org_id)}
        unique = set(ordered_ids)
        if len(unique) != len(ordered_ids) or unique != customs:
            raise InvalidRoleError("Role order must list every custom role.")
        total = len(ordered_ids)
        self._roles.set_role_positions(
            org_id,
            {rid: total - index for index, rid in enumerate(ordered_ids)},
        )
        self._access.record(
            org_id, actor_id, "role.reorder", "role", None, "allowed"
        )
        if ordered_ids:
            self._fan.catalog(org_id, ordered_ids[0], actor_id, detail="order")
