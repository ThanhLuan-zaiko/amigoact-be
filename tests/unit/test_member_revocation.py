"""Unit tests for MemberService.revoke_invitation with fake ports."""

from __future__ import annotations

import pytest

from core.exceptions import (
    ForbiddenError,
    InvalidMemberStateError,
    MemberNotFoundError,
)
from orgs.member_service import MemberService
from tests.unit.application_fakes import FakeApplications, FakeForms
from tests.unit.member_fakes import (
    NOW,
    FakeAccess,
    FakeEvents,
    FakeMembers,
    FakeOrgs,
    FakeUsers,
    _make_admin,
    _new_user,
    _service,
    _uid,
)


def test_revoke_invitation_lands_on_revoked() -> None:
    service, _, members, users, access, org_id, owner = _service()
    target = _new_user(users, "r@example.com")
    members.put(org_id, target, "invited", NOW)

    snap = service.revoke_invitation(org_id, owner, target)

    assert snap.status == "revoked"
    assert members.get(org_id, target).status == "revoked"
    assert access.audit[-1] == ("member.revoke", target, "allowed")


def test_revoke_requires_pending_invite() -> None:
    service, _, members, users, _, org_id, owner = _service()
    with pytest.raises(InvalidMemberStateError):
        service.revoke_invitation(org_id, owner, _uid())

    for state in ("active", "suspended", "left", "revoked"):
        member = _new_user(users, f"{state}@example.com")
        members.put(org_id, member, state, NOW)
        with pytest.raises(InvalidMemberStateError):
            service.revoke_invitation(org_id, owner, member)


def test_revoke_permission_matrix() -> None:
    service, _, members, users, access, org_id, owner = _service()
    admin = _new_user(users, "admin@example.com")
    _make_admin(members, access, org_id, admin)
    invited = _new_user(users, "i@example.com")
    members.put(org_id, invited, "invited", NOW)

    # member:invite holders withdraw plain invites themselves.
    snap = service.revoke_invitation(org_id, admin, invited)
    assert snap.status == "revoked"

    # A plain member cannot.
    plain = _new_user(users, "p@example.com")
    members.put(org_id, plain, "active", NOW)
    other = _new_user(users, "o@example.com")
    members.put(org_id, other, "invited", NOW)
    with pytest.raises(ForbiddenError):
        service.revoke_invitation(org_id, plain, other)
    assert access.audit[-1] == ("member.revoke", other, "denied")


def test_admin_cannot_revoke_admin_invite() -> None:
    service, _, members, users, access, org_id, owner = _service()
    admin = _new_user(users, "admin@example.com")
    _make_admin(members, access, org_id, admin)
    vip = _new_user(users, "vip@example.com")
    members.put(org_id, vip, "invited", NOW)
    access.assign(org_id, owner, vip, "admin")

    with pytest.raises(ForbiddenError):
        service.revoke_invitation(org_id, admin, vip)
    snap = service.revoke_invitation(org_id, owner, vip)
    assert snap.status == "revoked"
    # Role attached at invite time is cleaned up with the invite.
    assert "admin" not in access.roles.get((org_id, vip), set())


def test_revoked_can_be_reinvited_or_join() -> None:
    service, _, members, users, _, org_id, owner = _service()
    target = _new_user(users, "r@example.com")
    members.put(org_id, target, "revoked", NOW)
    assert service.invite_member(org_id, owner, "r@example.com").status == "invited"

    open_service, _, members2, users2, _, open_org, _ = _service("open")
    joiner = _new_user(users2, "j@example.com")
    members2.put(open_org, joiner, "revoked", NOW)
    assert open_service.join_org(open_org, joiner).status == "active"


def test_revoked_row_is_not_a_member() -> None:
    service, _, members, users, _, org_id, owner = _service()
    target = _new_user(users, "r@example.com")
    members.put(org_id, target, "revoked", NOW)
    with pytest.raises(MemberNotFoundError):
        service.remove_member(org_id, owner, target)
    with pytest.raises(MemberNotFoundError):
        service.update_member(org_id, owner, target, status="suspended")


def test_revoke_publishes_roster_and_inbox_events() -> None:
    orgs, members, users, access = (
        FakeOrgs(),
        FakeMembers(),
        FakeUsers(),
        FakeAccess(),
    )
    events = FakeEvents()
    org_id, owner = _uid(), _uid()
    orgs.add(org_id, owner)
    users.add(owner, "owner@example.com", "Owner")
    members.put(org_id, owner, "active", NOW)
    service = MemberService(
        orgs, members, users, access, events,
        forms=FakeForms(), applications=FakeApplications(),
    )

    target = _new_user(users, "r@example.com")
    members.put(org_id, target, "invited", NOW)
    service.revoke_invitation(org_id, owner, target)

    assert events.roster[-1] == (org_id, "revoked", target, owner, None)
    assert events.inbox[-1] == (target, "revoked", org_id, None)
