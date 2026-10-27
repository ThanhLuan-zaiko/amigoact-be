"""Role edits must reach the holders' own inbox, not only the roster channel."""

from __future__ import annotations

from rbac.roles_service import OrgRoleService
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
from tests.unit.role_fakes import FakeRoleRepo


def _setup():  # noqa: ANN202
    orgs, members, users, access = (
        FakeOrgs(),
        FakeMembers(),
        FakeUsers(),
        FakeAccess(),
    )
    roles, events = FakeRoleRepo(), FakeEvents()
    org_id, owner = _uid(), _uid()
    orgs.add(org_id, owner)
    users.add(owner, "owner@example.com", "Owner")
    members.put(org_id, owner, "active", NOW)
    service = OrgRoleService(
        orgs=orgs, members=members, roles=roles, access=access, events=events
    )
    holder = _new_user(users, "holder@example.com")
    members.put(org_id, holder, "active", NOW)
    return service, roles, events, org_id, owner, holder


def test_permission_change_notifies_each_holder() -> None:
    service, roles, events, org_id, owner, holder = _setup()
    view = service.create_role(org_id, owner, "Ops", "", ["activity:manage"])
    roles.assign_role(org_id, holder, view.id, owner, NOW)
    service.update_role(
        org_id, owner, view.id, permissions=["activity:create"]
    )
    assert events.inbox == [(holder, "role_catalog_changed", org_id, "Ops")]


def test_unchanged_permissions_and_rename_stay_quiet() -> None:
    service, roles, events, org_id, owner, holder = _setup()
    view = service.create_role(org_id, owner, "Ops", "", ["activity:manage"])
    roles.assign_role(org_id, holder, view.id, owner, NOW)
    service.update_role(
        org_id, owner, view.id, name="Ops2", permissions=["activity:manage"]
    )
    assert events.inbox == []


def test_actor_holding_the_role_is_not_notified() -> None:
    service, roles, events, org_id, owner, _ = _setup()
    view = service.create_role(org_id, owner, "Ops", "", ["activity:manage"])
    roles.assign_role(org_id, owner, view.id, owner, NOW)
    service.update_role(
        org_id, owner, view.id, permissions=["activity:create"]
    )
    assert events.inbox == []


def test_delete_notifies_holders_collected_before_the_purge() -> None:
    service, roles, events, org_id, owner, holder = _setup()
    view = service.create_role(org_id, owner, "Ops", "", ["activity:manage"])
    roles.assign_role(org_id, holder, view.id, owner, NOW)
    service.delete_role(org_id, owner, view.id)
    assert roles.list_org_assignments(org_id) == []
    assert events.inbox == [(holder, "role_catalog_changed", org_id, "Ops")]
