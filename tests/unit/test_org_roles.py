"""Unit tests for OrgRoleService: custom role CRUD plus delegation rules."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from core.exceptions import (
    ForbiddenError,
    InvalidRoleError,
    RoleNameTakenError,
    RoleNotFoundError,
)
from rbac.roles_service import MAX_ROLES_PER_ORG, OrgRoleService
from tests.unit.role_fakes import FakeRoleRepo
from tests.unit.member_fakes import (
    NOW,
    FakeAccess,
    FakeEvents,
    FakeMembers,
    FakeOrgs,
    FakeUsers,
    _new_user,
    _uid,
)

def _service() -> tuple[
    OrgRoleService, FakeOrgs, FakeMembers, FakeUsers, FakeAccess,
    FakeRoleRepo, UUID, UUID,
]:
    orgs, members, users, access = (
        FakeOrgs(),
        FakeMembers(),
        FakeUsers(),
        FakeAccess(),
    )
    roles = FakeRoleRepo()
    org_id, owner = _uid(), _uid()
    orgs.add(org_id, owner)
    users.add(owner, "owner@example.com", "Owner")
    members.put(org_id, owner, "active", NOW)
    service = OrgRoleService(
        orgs=orgs,
        members=members,
        roles=roles,
        access=access,
        events=FakeEvents(),
    )
    return service, orgs, members, users, access, roles, org_id, owner


def _manager(
    members: FakeMembers, access: FakeAccess, org_id: UUID, perms: set[str]
) -> UUID:
    uid = _uid()
    members.put(org_id, uid, "active", NOW)
    access.perms[(org_id, uid)] = set(perms)
    return uid


def test_list_roles_requires_membership() -> None:
    service, _, members, users, _, _, org_id, owner = _service()
    member = _new_user(users, "m@example.com")
    members.put(org_id, member, "active", NOW)
    rows = service.list_roles(org_id, member)
    assert [row.name for row in rows] == ["admin"]
    assert rows[0].is_system is True
    with pytest.raises(ForbiddenError):
        service.list_roles(org_id, _new_user(users, "x@example.com"))
    assert service.list_roles(org_id, owner)[0].name == "admin"


def test_owner_creates_and_lists_custom_role() -> None:
    service, _, members, users, _, roles, org_id, owner = _service()
    member = _new_user(users, "m@example.com")
    members.put(org_id, member, "active", NOW)
    view = service.create_role(
        org_id,
        owner,
        "Event Manager",
        "Runs events",
        ["activity:manage", "activity:create"],
    )
    assert view.name == "Event Manager"
    assert view.permissions == ["activity:create", "activity:manage"]
    assert view.member_count == 0
    assert view.is_system is False
    roles.assign_role(org_id, member, view.id, owner, NOW)
    rows = service.list_roles(org_id, owner)
    assert [row.name for row in rows] == ["admin", "Event Manager"]
    assert rows[1].member_count == 1


def test_create_rejects_bad_names_and_permissions() -> None:
    service, *_rest, org_id, owner = _service()
    for bad in ("admin", "OWNER", "member", "x"):
        with pytest.raises(InvalidRoleError):
            service.create_role(
                org_id, owner, bad, "", ["activity:manage"]
            )
    with pytest.raises(InvalidRoleError):
        service.create_role(org_id, owner, "Ops", "", [])
    with pytest.raises(InvalidRoleError):
        service.create_role(org_id, owner, "Ops", "", ["sudo:all"])
    with pytest.raises(InvalidRoleError):
        service.create_role(org_id, owner, "Ops", "", ["media:upload"])
    service.create_role(org_id, owner, "Ops", "", ["activity:manage"])
    with pytest.raises(RoleNameTakenError):
        service.create_role(org_id, owner, "ops", "", ["activity:manage"])


def test_manager_needs_role_assign_and_subset() -> None:
    service, _, members, _, access, _, org_id, _ = _service()
    plain = _manager(members, access, org_id, {"activity:manage"})
    with pytest.raises(ForbiddenError):
        service.create_role(
            org_id, plain, "Ops", "", ["activity:manage"]
        )
    delegate = _manager(
        members,
        access,
        org_id,
        {"member:role-assign", "activity:manage"},
    )
    with pytest.raises(ForbiddenError):
        service.create_role(
            org_id, delegate, "Ops", "", ["member:remove"]
        )
    view = service.create_role(
        org_id, delegate, "Ops", "", ["activity:manage"]
    )
    assert view.name == "Ops"


def test_update_role_rules() -> None:
    service, _, members, _, access, _, org_id, owner = _service()
    view = service.create_role(
        org_id, owner, "Ops", "", ["activity:manage"]
    )
    fresh = service.update_role(
        org_id, owner, view.id, name="Ops Crew", description="d"
    )
    assert fresh.name == "Ops Crew"
    other = service.create_role(
        org_id, owner, "Other", "", ["activity:view"]
    )
    with pytest.raises(RoleNameTakenError):
        service.update_role(org_id, owner, view.id, name="other")
    with pytest.raises(RoleNotFoundError):
        service.update_role(org_id, owner, _uid(), name="nope")
    # The system admin role is not an org custom role -> 404 either way.
    admin_id = service.list_roles(org_id, owner)[0].id
    with pytest.raises(RoleNotFoundError):
        service.update_role(org_id, owner, admin_id, name="x")
    with pytest.raises(RoleNotFoundError):
        service.delete_role(org_id, owner, admin_id)
    delegate = _manager(
        members,
        access,
        org_id,
        {"member:role-assign", "activity:manage"},
    )
    with pytest.raises(ForbiddenError):
        service.update_role(
            org_id, delegate, view.id, permissions=["member:remove"]
        )
    fresh = service.update_role(
        org_id, delegate, view.id, permissions=["activity:manage"]
    )
    assert fresh.permissions == ["activity:manage"]


def test_delete_role_purges_assignments() -> None:
    service, _, members, users, access, roles, org_id, owner = _service()
    member = _new_user(users, "m@example.com")
    members.put(org_id, member, "active", NOW)
    view = service.create_role(
        org_id, owner, "Ops", "", ["activity:manage"]
    )
    roles.assign_role(org_id, member, view.id, owner, NOW)
    service.delete_role(org_id, owner, view.id)
    assert service.list_roles(org_id, owner)[0].name == "admin"
    assert roles.list_org_assignments(org_id) == []
    with pytest.raises(RoleNotFoundError):
        service.delete_role(org_id, owner, view.id)


def test_delete_checks_subset_for_managers() -> None:
    service, _, members, _, access, _, org_id, owner = _service()
    rich = service.create_role(
        org_id, owner, "Rich", "", ["activity:manage", "member:remove"]
    )
    delegate = _manager(
        members,
        access,
        org_id,
        {"member:role-assign", "activity:manage"},
    )
    with pytest.raises(ForbiddenError):
        service.delete_role(org_id, delegate, rich.id)
    delegate2 = _manager(
        members,
        access,
        org_id,
        {"member:role-assign", "activity:manage", "member:remove"},
    )
    service.delete_role(org_id, delegate2, rich.id)


def test_max_roles_cap() -> None:
    service, *_rest, org_id, owner = _service()
    for index in range(MAX_ROLES_PER_ORG):
        service.create_role(
            org_id, owner, f"Role {index:02d}", "", ["activity:view"]
        )
    with pytest.raises(InvalidRoleError):
        service.create_role(org_id, owner, "One More", "", ["activity:view"])
