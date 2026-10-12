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
from core.ids import uuid7
from core.security import utcnow
from orgs.interfaces import MemberEvents, MemberRepository, OrgRepository
from orgs.model import Organization
from rbac.catalog import ASSIGNABLE_PERMISSIONS, RESERVED_ROLE_NAMES
from rbac.interfaces import AccessControl, RoleRepository
from rbac.model import Role

MAX_ROLES_PER_ORG = 20
NAME_MIN, NAME_MAX = 2, 40
DESCRIPTION_MAX = 200


@dataclass(frozen=True)
class OrgRoleView:
    """One role rendered for the org's role list (system + customs)."""

    id: UUID
    name: str
    description: str
    permissions: list[str]
    member_count: int
    is_system: bool


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
        self._events = events

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

    def _emit_catalog(
        self,
        org_id: UUID,
        role_id: UUID,
        actor_id: UUID,
        detail: str | None = None,
    ) -> None:
        """Best-effort roster refresh so every client reloads roles."""
        if self._events is None:
            return
        try:
            self._events.member_changed(
                org_id, "role_catalog_changed", role_id, actor_id,
                detail=detail,
            )
        except Exception:  # noqa: BLE001 - realtime is best-effort
            pass

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

    @staticmethod
    def _valid_description(description: str | None) -> str:
        clean = (description or "").strip()
        if len(clean) > DESCRIPTION_MAX:
            raise InvalidRoleError("Role description is invalid.")
        return clean

    @staticmethod
    def _valid_permissions(permissions: list[str] | None) -> set[str]:
        codes = set(permissions or [])
        if not codes or not codes <= ASSIGNABLE_PERMISSIONS:
            raise InvalidRoleError("Role permissions are invalid.")
        return codes

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
            key=lambda role: (role.name or "").casefold(),
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
    ) -> OrgRoleView:
        """Create a custom role; subset rule applies to non-owners."""
        org = self._live_org(org_id)
        self._require_role_manager(org, actor_id, "role.create")
        clean_name = self._valid_name(org_id, name, exclude=None)
        clean_description = self._valid_description(description)
        codes = self._valid_permissions(permissions)
        self._check_subset(org, actor_id, codes, "role.create")
        if len(self._roles.list_org_roles(org_id)) >= MAX_ROLES_PER_ORG:
            raise InvalidRoleError(
                "The org already has the maximum number of roles."
            )
        role = self._roles.create_org_role(
            org_id, uuid7(), clean_name, clean_description, utcnow()
        )
        self._roles.set_role_permissions(role.id, codes)
        self._access.record(
            org_id, actor_id, "role.create", "role", role.id, "allowed"
        )
        self._emit_catalog(org_id, role.id, actor_id, detail=role.name)
        return OrgRoleView(
            id=role.id,
            name=role.name,
            description=clean_description,
            permissions=sorted(codes),
            member_count=0,
            is_system=False,
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
    ) -> OrgRoleView:
        """Rename, re-describe or re-permission a custom role."""
        org = self._live_org(org_id)
        self._custom_role(org_id, role_id)
        self._require_role_manager(org, actor_id, "role.update", role_id)
        clean_name = (
            self._valid_name(org_id, name, exclude=role_id)
            if name is not None
            else None
        )
        clean_description = (
            self._valid_description(description)
            if description is not None
            else None
        )
        if permissions is not None:
            codes = self._valid_permissions(permissions)
            self._check_subset(
                org, actor_id, codes, "role.update", role_id
            )
            self._roles.set_role_permissions(role_id, codes)
        fresh = self._roles.update_org_role(
            org_id, role_id, clean_name, clean_description
        )
        assert fresh is not None
        self._access.record(
            org_id, actor_id, "role.update", "role", role_id, "allowed"
        )
        self._emit_catalog(org_id, role_id, actor_id, detail=fresh.name)
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
        held_perms = self._roles.list_role_permissions(role.id)
        self._check_subset(
            org, actor_id, held_perms, "role.delete", role_id
        )
        self._roles.delete_org_role(org_id, role_id)
        self._access.record(
            org_id, actor_id, "role.delete", "role", role_id, "allowed"
        )
        self._emit_catalog(org_id, role_id, actor_id, detail=role.name)
