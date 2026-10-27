"""In-memory role repository shared by the role service tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from rbac.interfaces import RoleRepository
from tests.unit.member_fakes import _uid

_ADMIN_PERMS = {
    "member:invite",
    "member:suspend",
    "member:remove",
    "member:view",
    "activity:view",
    "activity:create",
    "activity:manage",
}


class FakeRoleRepo(RoleRepository):
    """In-memory roles plus assignments for service-level tests."""

    def __init__(self) -> None:
        self.roles: dict[UUID, Any] = {}
        self.perms: dict[UUID, set[str]] = {}
        self.org_links: dict[UUID, list[UUID]] = {}
        self.assignments: list[Any] = []
        self.admin_id = _uid()
        self.roles[self.admin_id] = SimpleNamespace(
            id=self.admin_id,
            org_id=None,
            name="admin",
            description="",
            is_system=True,
        )
        self.perms[self.admin_id] = set(_ADMIN_PERMS)

    def get_role(self, role_id):  # noqa: ANN001, ANN202
        return self.roles.get(role_id)

    def resolve_role(self, org_id, name):  # noqa: ANN001, ANN202
        if name == "admin":
            return self.roles[self.admin_id]
        for role_id in self.org_links.get(org_id, []):
            role = self.roles.get(role_id)
            if role is not None and role.name == name:
                return role
        return None

    def list_role_permissions(self, role_id):  # noqa: ANN001, ANN202
        return set(self.perms.get(role_id, set()))

    def list_assignments(self, org_id, user_id):  # noqa: ANN001, ANN202
        return [
            row
            for row in self.assignments
            if row.org_id == org_id and row.user_id == user_id
        ]

    def list_org_assignments(self, org_id):  # noqa: ANN001, ANN202
        return [row for row in self.assignments if row.org_id == org_id]

    def assign_role(self, org_id, user_id, role_id, granted_by, now):  # noqa: ANN001, ANN202
        self.assignments.append(
            SimpleNamespace(
                org_id=org_id,
                user_id=user_id,
                role_id=role_id,
                expires_at=None,
            )
        )

    def revoke_role(self, org_id, user_id, role_id):  # noqa: ANN001, ANN202
        self.assignments = [
            row
            for row in self.assignments
            if not (
                row.org_id == org_id
                and row.user_id == user_id
                and row.role_id == role_id
            )
        ]

    def list_org_roles(self, org_id):  # noqa: ANN001, ANN202
        return [
            self.roles[role_id]
            for role_id in self.org_links.get(org_id, [])
            if role_id in self.roles
        ]

    def create_org_role(self, org_id, role_id, name, description, now, color="", position=0):  # noqa: ANN001, ANN202
        role = SimpleNamespace(
            id=role_id,
            org_id=org_id,
            name=name,
            description=description,
            is_system=False,
            color=color,
            position=position,
        )
        self.roles[role_id] = role
        self.org_links.setdefault(org_id, []).append(role_id)
        return role

    def set_role_positions(self, org_id, positions):  # noqa: ANN001, ANN202
        for role_id, position in positions.items():
            self.roles[role_id].position = position

    def update_org_role(self, org_id, role_id, name, description, color=None):  # noqa: ANN001, ANN202
        role = self.roles.get(role_id)
        if role is None or role.org_id != org_id or role.is_system:
            return None
        if color is not None:
            role.color = color
        if name is not None:
            role.name = name
        if description is not None:
            role.description = description
        return role

    def delete_org_role(self, org_id, role_id):  # noqa: ANN001, ANN202
        role = self.roles.get(role_id)
        if role is None or role.org_id != org_id or role.is_system:
            return False
        self.assignments = [
            row
            for row in self.assignments
            if not (row.org_id == org_id and row.role_id == role_id)
        ]
        self.perms.pop(role_id, None)
        del self.roles[role_id]
        self.org_links[org_id].remove(role_id)
        return True

    def set_role_permissions(self, role_id, codes):  # noqa: ANN001, ANN202
        self.perms[role_id] = set(codes)

    def count_role_holders(self, org_id):  # noqa: ANN001, ANN202
        counts: dict[UUID, int] = {}
        for row in self.assignments:
            if row.org_id == org_id:
                counts[row.role_id] = counts.get(row.role_id, 0) + 1
        return counts
