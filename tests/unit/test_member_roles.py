"""Unit tests for multi-role member updates and custom-role invites."""

from __future__ import annotations

import pytest

from core.exceptions import ForbiddenError, InvalidRoleError
from tests.unit.member_fakes import (
    NOW,
    _make_admin,
    _new_user,
    _service,
    _uid,
)


def _delegate(service, members, access, org_id, users, perms):
    """Active member holding an explicit permission set (e.g. role-assign)."""
    uid = _new_user(users, f"d-{_uid()}@example.com")
    members.put(org_id, uid, "active", NOW)
    access.perms[(org_id, uid)] = set(perms)
    return uid


def test_owner_replaces_roles_with_custom_set() -> None:
    service, _, members, users, access, org_id, owner = _service()
    access.role_perms[(org_id, "coordinator")] = {"activity:manage"}
    target = _new_user(users, "t@example.com")
    members.put(org_id, target, "active", NOW)

    snap = service.update_member(
        org_id, owner, target, roles=["coordinator"]
    )
    assert snap.roles == ["coordinator"]
    assert "coordinator" in access.roles.get((org_id, target), set())
    events = service._events.roster  # noqa: SLF001
    assert (org_id, "role_granted", target, owner, "coordinator") in events


def test_owner_assigns_multiple_roles() -> None:
    service, _, members, users, access, org_id, owner = _service()
    access.role_perms[(org_id, "coordinator")] = {"activity:manage"}
    target = _new_user(users, "t@example.com")
    members.put(org_id, target, "active", NOW)

    snap = service.update_member(
        org_id, owner, target, roles=["admin", "coordinator"]
    )
    assert snap.roles == ["admin", "coordinator"]


def test_empty_roles_strips_everything() -> None:
    service, _, members, users, access, org_id, owner = _service()
    target = _new_user(users, "t@example.com")
    _make_admin(members, access, org_id, target)

    snap = service.update_member(org_id, owner, target, roles=[])
    assert snap.roles == []
    assert "admin" not in access.roles.get((org_id, target), set())


def test_delegate_assigns_within_subset_only() -> None:
    service, _, members, users, access, org_id, owner = _service()
    access.role_perms[(org_id, "coordinator")] = {"activity:manage"}
    access.role_perms[(org_id, "bouncer")] = {"member:remove"}
    delegate = _delegate(
        service, members, access, org_id, users,
        {"member:role-assign", "activity:manage"},
    )
    target = _new_user(users, "t@example.com")
    members.put(org_id, target, "active", NOW)

    snap = service.update_member(
        org_id, delegate, target, roles=["coordinator"]
    )
    assert snap.roles == ["coordinator"]
    with pytest.raises(ForbiddenError):
        service.update_member(org_id, delegate, target, roles=["bouncer"])
    with pytest.raises(ForbiddenError):
        service.update_member(
            org_id, delegate, target, roles=["coordinator", "admin"]
        )


def test_delegate_cannot_strip_admin() -> None:
    service, _, members, users, access, org_id, owner = _service()
    access.role_perms[(org_id, "coordinator")] = {"activity:manage"}
    delegate = _delegate(
        service, members, access, org_id, users,
        {"member:role-assign", "activity:manage"},
    )
    admin = _new_user(users, "a@example.com")
    _make_admin(members, access, org_id, admin)

    with pytest.raises(ForbiddenError):
        service.update_member(org_id, delegate, admin, roles=[])
    with pytest.raises(ForbiddenError):
        service.update_member(
            org_id, delegate, admin, roles=["coordinator"]
        )


def test_plain_member_cannot_assign_roles() -> None:
    service, _, members, users, access, org_id, _ = _service()
    access.role_perms[(org_id, "coordinator")] = {"activity:manage"}
    plain = _new_user(users, "p@example.com")
    members.put(org_id, plain, "active", NOW)
    target = _new_user(users, "t@example.com")
    members.put(org_id, target, "active", NOW)
    with pytest.raises(ForbiddenError):
        service.update_member(
            org_id, plain, target, roles=["coordinator"]
        )


def test_unknown_role_name_rejected() -> None:
    service, _, members, users, _, org_id, owner = _service()
    target = _new_user(users, "t@example.com")
    members.put(org_id, target, "active", NOW)
    with pytest.raises(InvalidRoleError):
        service.update_member(org_id, owner, target, roles=["ghost"])
    with pytest.raises(InvalidRoleError):
        service.update_member(org_id, owner, target, roles=["owner"])


def test_invite_with_custom_role() -> None:
    service, _, members, users, access, org_id, owner = _service()
    access.role_perms[(org_id, "coordinator")] = {"activity:manage"}
    vip = _new_user(users, "vip@example.com")

    snap = service.invite_member(
        org_id, owner, "vip@example.com", role="coordinator"
    )
    assert snap.roles == ["coordinator"]
    assert "coordinator" in access.roles.get((org_id, vip), set())


def test_delegate_invite_within_subset() -> None:
    service, _, members, users, access, org_id, _ = _service()
    access.role_perms[(org_id, "coordinator")] = {"activity:manage"}
    access.role_perms[(org_id, "bouncer")] = {"member:remove"}
    delegate = _delegate(
        service, members, access, org_id, users,
        {"member:role-assign", "activity:manage", "member:invite"},
    )
    _new_user(users, "a@example.com")
    _new_user(users, "b@example.com")

    snap = service.invite_member(
        org_id, delegate, "a@example.com", role="coordinator"
    )
    assert snap.roles == ["coordinator"]
    with pytest.raises(ForbiddenError):
        service.invite_member(
            org_id, delegate, "b@example.com", role="bouncer"
        )
    with pytest.raises(ForbiddenError):
        service.invite_member(
            org_id, delegate, "b@example.com", role="admin"
        )
