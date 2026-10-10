"""Authorization facade: grants + roles + expiry combined, plus audit."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from core.exceptions import InvalidRoleError
from core.security import utcnow
from rbac.interfaces import AccessControl, AuditWriter, GrantRepository, RoleRepository

logger = logging.getLogger("amigoact.rbac")


def _expired(row: object) -> bool:
    """True when the row carries an expires_at already in the past."""
    expires = getattr(row, "expires_at", None)
    if expires is None:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires <= utcnow()


class AccessControlService(AccessControl):
    """Combines role permissions AND direct grants (never denies via grant)."""

    def __init__(
        self,
        roles: RoleRepository,
        grants: GrantRepository,
        audit: AuditWriter,
    ) -> None:
        self._roles = roles
        self._grants = grants
        self._audit = audit

    def has_permission(
        self, org_id: UUID, user_id: UUID, permission: str
    ) -> bool:
        grant = self._grants.get_grant(org_id, user_id, permission)
        if grant is not None and not _expired(grant):
            return True
        for assignment in self._roles.list_assignments(org_id, user_id):
            if _expired(assignment):
                continue
            if permission in self._roles.list_role_permissions(
                assignment.role_id
            ):
                return True
        return False

    def role_names_of(self, org_id: UUID, user_id: UUID) -> list[str]:
        names: list[str] = []
        for assignment in self._roles.list_assignments(org_id, user_id):
            if _expired(assignment):
                continue
            role = self._roles.get_role(assignment.role_id)
            if role is not None:
                names.append(role.name)
        return names

    def role_map(self, org_id: UUID) -> dict[UUID, list[str]]:
        result: dict[UUID, list[str]] = {}
        for assignment in self._roles.list_org_assignments(org_id):
            if _expired(assignment):
                continue
            role = self._roles.get_role(assignment.role_id)
            if role is None:
                continue
            result.setdefault(assignment.user_id, []).append(role.name)
        return result

    def assign(
        self, org_id: UUID, actor_id: UUID, user_id: UUID, role_name: str
    ) -> None:
        role = self._roles.resolve_role(org_id, role_name)
        if role is None:
            raise InvalidRoleError("Role is unknown.")
        held = {row.role_id for row in self._roles.list_assignments(org_id, user_id)}
        if role.id in held:
            return
        self._roles.assign_role(org_id, user_id, role.id, actor_id, utcnow())

    def revoke(self, org_id: UUID, user_id: UUID, role_name: str) -> None:
        role = self._roles.resolve_role(org_id, role_name)
        if role is None:
            return
        self._roles.revoke_role(org_id, user_id, role.id)

    def record(
        self,
        org_id: UUID,
        actor_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        result: str,
    ) -> None:
        try:
            self._audit.record(
                org_id,
                actor_id,
                action,
                resource_type,
                resource_id,
                result,
                utcnow(),
            )
        except Exception:
            # Audit must never break the request path.
            logger.warning("access audit write failed", exc_info=True)
