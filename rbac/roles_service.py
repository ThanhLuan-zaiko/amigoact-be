"""Org-scoped custom roles: CRUD rules, delegation guard, audit, fan-out."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from core.exceptions import (
    ForbiddenError,
    InvalidRoleError,
    NotFoundError,
    OrgDeletedError,
    RoleNameTakenError,
    RoleNotFoundError,
)
from core.exceptions_roles import RoleHierarchyError
from core.ids import uuid7
from core.security import utcnow
from orgs.interfaces import MemberEvents, MemberRepository, OrgRepository
from orgs.model import Organization
from rbac.catalog import RESERVED_ROLE_NAMES
from rbac.interfaces import AccessControl, RoleRepository
from rbac.model import Role
from rbac.role_events import RoleFanOut
from rbac.role_rules import (
    valid_color,
    valid_description,
    valid_permissions,
)

MAX_ROLES_PER_ORG = 20
NAME_MIN, NAME_MAX = 2, 40


@dataclass(frozen=True)
class OrgRoleView:
    """One role rendered for the org's role list (system + customs)."""

    id: UUID
    name: str
    description: str
    permissions: list[str]
    member_count: int
    is_system: bool
    color: str = ""
    position: int = 0


class OrgRoleService:
    """Custom role CRUD; owner or member:role-assign holders manage.

    Delegation guard: a non-owner assigner may only hand out permissions
    they already hold (role permission set must be a subset of theirs),
    and the system "admin" role always stays owner-only.
    """

    def __init__(
        self,
        orgs: OrgRepository,
        members: MemberRepository,
        roles: RoleRepository,
        access: AccessControl,
        events: MemberEvents | None = None,
    ) -> None:
        self._orgs = orgs
        self._members = members
        self._roles = roles
        self._access = access
        self._fan = RoleFanOut(events)

    def _live_org(self, org_id: UUID) -> Organization:
        org = self._orgs.get_by_id(org_id)
        if org is None:
            raise NotFoundError("Organization not found.")
        if getattr(org, "deleted_at", None) is not None:
            raise OrgDeletedError("Organization is soft-deleted.")
        return org

    def _active_member(self, org_id: UUID, user_id: UUID) -> bool:
        row = self._members.get(org_id, user_id)
        return (
            row is not None
            and (getattr(row, "status", "active") or "active") == "active"
        )

    def _require_role_manager(
        self,
        org: Organization,
        actor_id: UUID,
        action: str,
        role_id: UUID | None = None,
    ) -> None:
        """Owner passes; others need membership AND member:role-assign."""
        if org.owner_id == actor_id:
            return
        if self._active_member(
            org.id, actor_id
        ) and self._access.has_permission(
            org.id, actor_id, "member:role-assign"
        ):
            return
        self._access.record(
            org.id, actor_id, action, "role", role_id, "denied"
        )
        raise ForbiddenError("Only org managers can do this.")

    def _check_subset(
        self,
        org: Organization,
        actor_id: UUID,
        permissions: set[str],
        action: str,
        role_id: UUID | None = None,
    ) -> None:
        """Non-owners may only delegate permissions they already hold."""
        if org.owner_id == actor_id:
            return
        held = self._access.effective_permissions(org.id, actor_id)
        if not permissions <= held:
            self._access.record(
                org.id, actor_id, action, "role", role_id, "denied"
            )
            raise ForbiddenError(
                "You can only delegate permissions you hold."
            )

    def _holders(self, org_id: UUID, role_id: UUID) -> set[UUID]:
        """Users currently holding one role (read before a delete wipes it)."""
        return {
            row.user_id
            for row in self._roles.list_org_assignments(org_id)
            if row.role_id == role_id
        }

    def _require_below(
        self, org: Organization, actor_id: UUID, role: Role, action: str
    ) -> None:
        """Hierarchy: a non-owner may only touch roles under their top role.

        Actors holding no ranked role (e.g. a direct grant) are not limited
        beyond the delegation subset rule.
        """
        if org.owner_id == actor_id:
            return
        ceiling = self._access.role_ceiling(org.id, actor_id)
        rank = int(getattr(role, "position", 0) or 0)
        if ceiling is not None and rank >= ceiling:
            self._access.record(
                org.id, actor_id, action, "role", role.id, "denied"
            )
            raise RoleHierarchyError("Role ranks at or above your own.")

    def _view(
        self, role: Role, counts: dict[UUID, int], *, is_system: bool
    ) -> OrgRoleView:
        return OrgRoleView(
            id=role.id,
            name=role.name,
            description=getattr(role, "description", "") or "",
            permissions=sorted(self._roles.list_role_permissions(role.id)),
            member_count=counts.get(role.id, 0),
            is_system=is_system,
            color=getattr(role, "color", "") or "",
            position=int(getattr(role, "position", 0) or 0),
        )

    def _valid_name(
        self, org_id: UUID, name: str | None, exclude: UUID | None
    ) -> str:
        clean = (name or "").strip()
        if not (NAME_MIN <= len(clean) <= NAME_MAX):
            raise InvalidRoleError("Role name is invalid.")
        folded = clean.casefold()
        if folded in RESERVED_ROLE_NAMES:
            raise InvalidRoleError("Role name is reserved.")
        for role in self._roles.list_org_roles(org_id):
            if role.id == exclude:
                continue
            if (role.name or "").casefold() == folded:
                raise RoleNameTakenError("Role name is taken.")
        return clean

    def list_roles(self, org_id: UUID, viewer_id: UUID) -> list[OrgRoleView]:
        """System admin plus org customs; any active member may read."""
        org = self._live_org(org_id)
        if org.owner_id != viewer_id and not self._active_member(
            org_id, viewer_id
        ):
            self._access.record(
                org_id, viewer_id, "role.list", "role", None, "denied"
            )
            raise ForbiddenError("Only org members can view roles.")
        counts = self._roles.count_role_holders(org_id)
        out: list[OrgRoleView] = []
        admin = self._roles.resolve_role(org_id, "admin")
        if admin is not None:
            out.append(self._view(admin, counts, is_system=True))
        customs = sorted(
            self._roles.list_org_roles(org_id),
            key=lambda role: (
                -int(getattr(role, "position", 0) or 0),
                (role.name or "").casefold(),
            ),
        )
        out.extend(
            self._view(role, counts, is_system=False) for role in customs
        )
        return out

    def create_role(
        self,
        org_id: UUID,
        actor_id: UUID,
        name: str,
        description: str,
        permissions: list[str],
        color: str = "",
    ) -> OrgRoleView:
        """Create a custom role at the bottom rank; subset rule applies."""
        org = self._live_org(org_id)
        self._require_role_manager(org, actor_id, "role.create")
        clean_name = self._valid_name(org_id, name, exclude=None)
        clean_description = valid_description(description)
        codes = valid_permissions(permissions)
        clean_color = valid_color(color) or ""
        self._check_subset(org, actor_id, codes, "role.create")
        existing = self._roles.list_org_roles(org_id)
        if len(existing) >= MAX_ROLES_PER_ORG:
            raise InvalidRoleError(
                "The org already has the maximum number of roles."
            )
        # New roles start below every existing one, so whoever creates a
        # role (holding any ranked role) can still manage it afterwards.
        ranks = [int(getattr(row, "position", 0) or 0) for row in existing]
        role = self._roles.create_org_role(
            org_id, uuid7(), clean_name, clean_description, utcnow(),
            color=clean_color, position=min(ranks) - 1 if ranks else 0,
        )
        self._roles.set_role_permissions(role.id, codes)
        self._access.record(
            org_id, actor_id, "role.create", "role", role.id, "allowed"
        )
        self._fan.catalog(org_id, role.id, actor_id, detail=role.name)
        return OrgRoleView(
            id=role.id,
            name=role.name,
            description=clean_description,
            permissions=sorted(codes),
            member_count=0,
            is_system=False,
            color=clean_color,
            position=int(getattr(role, "position", 0) or 0),
        )

    def _custom_role(self, org_id: UUID, role_id: UUID) -> Role:
        role = self._roles.get_role(role_id)
        if role is None or role.org_id != org_id:
            raise RoleNotFoundError("Role not found.")
        if getattr(role, "is_system", False):
            raise ForbiddenError("System roles cannot be modified.")
        return role

    def update_role(
        self,
        org_id: UUID,
        actor_id: UUID,
        role_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        permissions: list[str] | None = None,
        color: str | None = None,
    ) -> OrgRoleView:
        """Rename, re-describe, recolour or re-permission a custom role."""
        org = self._live_org(org_id)
        target = self._custom_role(org_id, role_id)
        self._require_role_manager(org, actor_id, "role.update", role_id)
        self._require_below(org, actor_id, target, "role.update")
        clean_color = valid_color(color)
        clean_name = (
            self._valid_name(org_id, name, exclude=role_id)
            if name is not None
            else None
        )
        clean_description = (
            valid_description(description)
            if description is not None
            else None
        )
        perms_changed = False
        if permissions is not None:
            codes = valid_permissions(permissions)
            self._check_subset(
                org, actor_id, codes, "role.update", role_id
            )
            perms_changed = codes != self._roles.list_role_permissions(role_id)
            self._roles.set_role_permissions(role_id, codes)
        fresh = self._roles.update_org_role(
            org_id, role_id, clean_name, clean_description, color=clean_color
        )
        assert fresh is not None
        self._access.record(
            org_id, actor_id, "role.update", "role", role_id, "allowed"
        )
        self._fan.catalog(org_id, role_id, actor_id, detail=fresh.name)
        if perms_changed:
            self._fan.notify(
                org_id, self._holders(org_id, role_id), actor_id, fresh.name
            )
        return self._view(
            fresh, self._roles.count_role_holders(org_id), is_system=False
        )

    def delete_role(
        self, org_id: UUID, actor_id: UUID, role_id: UUID
    ) -> None:
        """Drop a custom role and every assignment it had."""
        org = self._live_org(org_id)
        role = self._custom_role(org_id, role_id)
        self._require_role_manager(org, actor_id, "role.delete", role_id)
        self._require_below(org, actor_id, role, "role.delete")
        held_perms = self._roles.list_role_permissions(role.id)
        self._check_subset(
            org, actor_id, held_perms, "role.delete", role_id
        )
        holders = self._holders(org_id, role_id)
        self._roles.delete_org_role(org_id, role_id)
        self._access.record(
            org_id, actor_id, "role.delete", "role", role_id, "allowed"
        )
        self._fan.catalog(org_id, role_id, actor_id, detail=role.name)
        self._fan.notify(org_id, holders, actor_id, role.name)
