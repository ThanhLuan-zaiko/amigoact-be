"""Unit tests for AccessControlService with fake repositories."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
import uuid_utils

from core.exceptions import InvalidRoleError
from rbac.interfaces import AuditWriter, GrantRepository, RoleRepository
from rbac.service import AccessControlService


def _uid() -> UUID:
    return UUID(str(uuid_utils.uuid7()))


def _role(role_id: UUID, name: str) -> Any:
    return SimpleNamespace(
        id=role_id, org_id=None, name=name, description="", is_system=True
    )


class FakeRoles(RoleRepository):
    def __init__(self) -> None:
        self.roles: dict[UUID, Any] = {}
        self.by_name: dict[tuple[UUID, str], UUID] = {}
        self.perms: dict[UUID, set[str]] = {}
        self.assignments: list[Any] = []

    def get_role(self, role_id):  # noqa: ANN001, ANN202
        return self.roles.get(role_id)

    def resolve_role(self, org_id, name):  # noqa: ANN001, ANN202
        role_id = self.by_name.get((org_id, name)) or self.by_name.get(
            (UUID(int=0), name)
        )
        return self.roles.get(role_id) if role_id else None

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
                granted_at=now,
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
        raise NotImplementedError

    def create_org_role(self, org_id, role_id, name, description, now):  # noqa: ANN001, ANN202
        raise NotImplementedError

    def update_org_role(self, org_id, role_id, name, description):  # noqa: ANN001, ANN202
        raise NotImplementedError

    def delete_org_role(self, org_id, role_id):  # noqa: ANN001, ANN202
        raise NotImplementedError

    def set_role_permissions(self, role_id, codes):  # noqa: ANN001, ANN202
        raise NotImplementedError

    def count_role_holders(self, org_id):  # noqa: ANN001, ANN202
        raise NotImplementedError


class FakeGrants(GrantRepository):
    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, UUID, str], Any] = {}

    def get_grant(self, org_id, user_id, permission_code):  # noqa: ANN001, ANN202
        return self.rows.get((org_id, user_id, permission_code))

    def list_grants(self, org_id, user_id):  # noqa: ANN001, ANN202
        return [
            SimpleNamespace(permission_code=code, expires_at=row.expires_at)
            for (oid, uid, code), row in self.rows.items()
            if oid == org_id and uid == user_id
        ]


class FakeAudit(AuditWriter):
    def __init__(self, fail: bool = False) -> None:
        self.rows: list[tuple] = []
        self._fail = fail

    def record(self, org_id, actor_id, action, resource_type, resource_id, result, now):  # noqa: ANN001, ANN202
        if self._fail:
            raise RuntimeError("audit offline")
        self.rows.append((org_id, actor_id, action, resource_type, resource_id, result))


def _service() -> tuple[AccessControlService, FakeRoles, FakeGrants, FakeAudit]:
    roles, grants, audit = FakeRoles(), FakeGrants(), FakeAudit()
    return AccessControlService(roles, grants, audit), roles, grants, audit


def _seed_admin(roles: FakeRoles, org_id: UUID) -> UUID:
    """Register an admin role resolvable for one org."""
    role_id = _uid()
    roles.roles[role_id] = _role(role_id, "admin")
    roles.by_name[(UUID(int=0), "admin")] = role_id
    roles.perms[role_id] = {"member:invite", "member:remove"}
    return role_id


def test_role_permission_grants_access() -> None:
    service, roles, _, _ = _service()
    org, user = _uid(), _uid()
    role_id = _seed_admin(roles, org)
    roles.assign_role(org, user, role_id, _uid(), datetime.now(timezone.utc))
    assert service.has_permission(org, user, "member:invite") is True
    assert service.has_permission(org, user, "org:update") is False


def test_direct_grant_wins_without_role() -> None:
    service, _, grants, _ = _service()
    org, user = _uid(), _uid()
    grants.rows[(org, user, "member:remove")] = SimpleNamespace(
        expires_at=None
    )
    assert service.has_permission(org, user, "member:remove") is True
    assert service.has_permission(org, user, "member:invite") is False


def test_expired_grant_falls_back_to_roles() -> None:
    service, _, grants, _ = _service()
    org, user = _uid(), _uid()
    grants.rows[(org, user, "member:invite")] = SimpleNamespace(
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1)
    )
    assert service.has_permission(org, user, "member:invite") is False


def test_expired_assignment_is_ignored() -> None:
    service, roles, _, _ = _service()
    org, user = _uid(), _uid()
    role_id = _seed_admin(roles, org)
    roles.assignments.append(
        SimpleNamespace(
            org_id=org,
            user_id=user,
            role_id=role_id,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    assert service.has_permission(org, user, "member:invite") is False
    assert service.role_names_of(org, user) == []


def test_no_permission_no_grant_denies() -> None:
    service, _, _, _ = _service()
    assert service.has_permission(_uid(), _uid(), "member:invite") is False


def test_assign_and_revoke_named_role() -> None:
    service, roles, _, _ = _service()
    org, user = _uid(), _uid()
    role_id = _seed_admin(roles, org)
    service.assign(org, _uid(), user, "admin")
    assert service.role_names_of(org, user) == ["admin"]
    service.assign(org, _uid(), user, "admin")  # idempotent
    held = [row for row in roles.assignments if row.user_id == user]
    assert len(held) == 1
    service.revoke(org, user, "admin")
    assert service.role_names_of(org, user) == []
    assert roles.get_role(role_id) is not None  # role catalog untouched


def test_assign_unknown_role_raises() -> None:
    service, _, _, _ = _service()
    with pytest.raises(InvalidRoleError):
        service.assign(_uid(), _uid(), _uid(), "superadmin")


def test_role_map_covers_whole_org() -> None:
    service, roles, _, _ = _service()
    org, one, two = _uid(), _uid(), _uid()
    role_id = _seed_admin(roles, org)
    for user in (one, two):
        roles.assign_role(org, user, role_id, _uid(), datetime.now(timezone.utc))
    mapping = service.role_map(org)
    assert mapping[one] == ["admin"]
    assert mapping[two] == ["admin"]


def test_record_delegates_to_audit_writer() -> None:
    service, _, _, audit = _service()
    org, user = _uid(), _uid()
    service.record(org, user, "member.invite", "member", None, "allowed")
    assert audit.rows[0][2] == "member.invite"
    assert audit.rows[0][5] == "allowed"


def test_record_survives_broken_audit_store() -> None:
    service, _, _, _ = _service()
    service._audit = FakeAudit(fail=True)  # noqa: SLF001
    service.record(_uid(), _uid(), "member.invite", "member", None, "allowed")
