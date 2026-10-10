"""Unit tests for MemberService with fake ports (no I/O, fast)."""

from __future__ import annotations

import pytest

from core.exceptions import (
    AlreadyInvitedError,
    AlreadyMemberError,
    ForbiddenError,
    InvalidMemberStateError,
    InviteOnlyError,
    UserNotFoundError,
)
from tests.unit.member_fakes import (
    NOW,
    _make_admin,
    _new_user,
    _service,
    _uid,
)


def test_invite_by_owner_creates_invited() -> None:
    service, _, members, users, access, org_id, owner = _service()
    target = _new_user(users, "new@example.com")
    snap = service.invite_member(org_id, owner, "new@example.com")
    assert snap.status == "invited"
    assert snap.email == "new@example.com"
    assert members.get(org_id, target).status == "invited"
    assert access.audit[-1] == ("member.invite", target, "allowed")


def test_invite_by_admin_allowed_member_denied() -> None:
    service, _, members, users, access, org_id, owner = _service()
    admin = _new_user(users, "admin@example.com")
    _make_admin(members, access, org_id, admin)
    _new_user(users, "t@example.com")
    assert service.invite_member(org_id, admin, "t@example.com").status == "invited"

    plain = _new_user(users, "plain@example.com")
    members.put(org_id, plain, "active", NOW)
    _new_user(users, "x@example.com")
    with pytest.raises(ForbiddenError):
        service.invite_member(org_id, plain, "x@example.com")
    assert access.audit[-1][2] == "denied"


def test_invite_unknown_or_suspended_email() -> None:
    service, _, _, users, _, org_id, owner = _service()
    with pytest.raises(UserNotFoundError):
        service.invite_member(org_id, owner, "ghost@example.com")
    _new_user(users, "off@example.com", status="suspended")
    with pytest.raises(UserNotFoundError):
        service.invite_member(org_id, owner, "off@example.com")


def test_invite_guards_member_states() -> None:
    service, _, members, users, _, org_id, owner = _service()
    active = _new_user(users, "a@example.com")
    members.put(org_id, active, "active", NOW)
    with pytest.raises(AlreadyMemberError):
        service.invite_member(org_id, owner, "a@example.com")
    with pytest.raises(AlreadyMemberError):
        service.invite_member(org_id, owner, "owner@example.com")

    invited = _new_user(users, "i@example.com")
    members.put(org_id, invited, "invited", NOW)
    with pytest.raises(AlreadyInvitedError):
        service.invite_member(org_id, owner, "i@example.com")


def test_reinvite_after_left() -> None:
    service, _, members, users, _, org_id, owner = _service()
    target = _new_user(users, "gone@example.com")
    members.put(org_id, target, "left", NOW)
    snap = service.invite_member(org_id, owner, "gone@example.com")
    assert snap.status == "invited"


def test_invite_as_admin_owner_only() -> None:
    service, _, members, users, access, org_id, owner = _service()
    admin = _new_user(users, "admin@example.com")
    _make_admin(members, access, org_id, admin)
    target = _new_user(users, "vip@example.com")
    with pytest.raises(ForbiddenError):
        service.invite_member(org_id, admin, "vip@example.com", role="admin")
    snap = service.invite_member(org_id, owner, "vip@example.com", role="admin")
    assert snap.role == "admin"
    assert "admin" in access.roles.get((org_id, target), set())


def test_accept_and_decline_invitations() -> None:
    service, _, members, users, _, org_id, owner = _service()
    one = _new_user(users, "one@example.com")
    members.put(org_id, one, "invited", NOW)
    assert service.accept_invitation(org_id, one).status == "active"
    with pytest.raises(InvalidMemberStateError):
        service.accept_invitation(org_id, one)

    two = _new_user(users, "two@example.com")
    members.put(org_id, two, "invited", NOW)
    assert service.decline_invitation(org_id, two).status == "left"
    with pytest.raises(InvalidMemberStateError):
        service.decline_invitation(org_id, two)
    with pytest.raises(InvalidMemberStateError):
        service.accept_invitation(org_id, _uid())


def test_join_policy_open_vs_invite() -> None:
    invite_service, _, members, users, _, org_id, _ = _service("invite")
    stranger = _new_user(users, "s@example.com")
    with pytest.raises(InviteOnlyError):
        invite_service.join_org(org_id, stranger)

    open_service, _, members2, users2, _, open_org, _ = _service("open")
    joiner = _new_user(users2, "j@example.com")
    snap = open_service.join_org(open_org, joiner)
    assert snap.status == "active"
    with pytest.raises(AlreadyMemberError):
        open_service.join_org(open_org, joiner)

    suspended = _new_user(users2, "sp@example.com")
    members2.put(open_org, suspended, "suspended", NOW)
    with pytest.raises(AlreadyMemberError):
        open_service.join_org(open_org, suspended)

    left = _new_user(users2, "l@example.com")
    members2.put(open_org, left, "left", NOW)
    assert open_service.join_org(open_org, left).status == "active"
