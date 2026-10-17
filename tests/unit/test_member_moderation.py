"""Unit tests for member moderation: suspend, roles, remove, listing."""

from __future__ import annotations

import pytest

from core.exceptions import (
    ForbiddenError,
    InvalidMemberStateError,
    MemberNotFoundError,
    OwnerImmutableError,
)
from tests.unit.member_fakes import (
    NOW,
    _make_admin,
    _new_user,
    _service,
    _uid,
)
from tests.unit.org_fakes import FakeMedia


def test_suspend_reactivate_matrix() -> None:
    service, _, members, users, access, org_id, owner = _service()
    admin = _new_user(users, "admin@example.com")
    _make_admin(members, access, org_id, admin)
    target = _new_user(users, "t@example.com")
    members.put(org_id, target, "active", NOW)

    snap = service.update_member(org_id, admin, target, status="suspended")
    assert snap.status == "suspended"
    snap = service.update_member(org_id, admin, target, status="active")
    assert snap.status == "active"

    with pytest.raises(InvalidMemberStateError):
        service.update_member(org_id, owner, target, status="active")

    invited = _new_user(users, "i@example.com")
    members.put(org_id, invited, "invited", NOW)
    with pytest.raises(InvalidMemberStateError):
        service.update_member(org_id, owner, invited, status="suspended")

    plain = _new_user(users, "p@example.com")
    members.put(org_id, plain, "active", NOW)
    with pytest.raises(ForbiddenError):
        service.update_member(org_id, plain, target, status="suspended")


def test_admin_cannot_touch_admin() -> None:
    service, _, members, users, access, org_id, owner = _service()
    first = _new_user(users, "a1@example.com")
    second = _new_user(users, "a2@example.com")
    _make_admin(members, access, org_id, first)
    _make_admin(members, access, org_id, second)
    with pytest.raises(ForbiddenError):
        service.update_member(org_id, first, second, status="suspended")
    with pytest.raises(ForbiddenError):
        service.remove_member(org_id, first, second)
    assert service.update_member(org_id, owner, second, status="suspended").status == "suspended"


def test_role_assign_owner_only() -> None:
    service, _, members, users, access, org_id, owner = _service()
    admin = _new_user(users, "admin@example.com")
    _make_admin(members, access, org_id, admin)
    target = _new_user(users, "t@example.com")
    members.put(org_id, target, "active", NOW)

    with pytest.raises(ForbiddenError):
        service.update_member(org_id, admin, target, role="admin")
    snap = service.update_member(org_id, owner, target, role="admin")
    assert snap.roles == ["admin"]
    snap = service.update_member(org_id, owner, target, role="member")
    assert snap.roles == []
    assert "admin" not in access.roles.get((org_id, target), set())


def test_remove_and_leave_rules() -> None:
    service, _, members, users, access, org_id, owner = _service()
    admin = _new_user(users, "admin@example.com")
    _make_admin(members, access, org_id, admin)
    target = _new_user(users, "t@example.com")
    members.put(org_id, target, "active", NOW)

    service.remove_member(org_id, admin, target)
    assert members.get(org_id, target).status == "left"
    assert access.audit[-1][0] == "member.remove"
    with pytest.raises(MemberNotFoundError):
        service.remove_member(org_id, owner, target)
    with pytest.raises(MemberNotFoundError):
        service.remove_member(org_id, owner, _uid())

    leaver = _new_user(users, "lv@example.com")
    members.put(org_id, leaver, "active", NOW)
    service.remove_member(org_id, leaver, leaver)
    assert members.get(org_id, leaver).status == "left"
    assert access.audit[-1][0] == "member.leave"

    with pytest.raises(OwnerImmutableError):
        service.remove_member(org_id, owner, owner)
    with pytest.raises(OwnerImmutableError):
        service.remove_member(org_id, admin, owner)


def test_owner_immutable_on_update() -> None:
    service, _, members, users, access, org_id, owner = _service()
    with pytest.raises(OwnerImmutableError):
        service.update_member(org_id, owner, owner, status="suspended")
    with pytest.raises(OwnerImmutableError):
        service.update_member(org_id, owner, owner, role="member")


def test_member_viewer_sees_active_only_without_email() -> None:
    service, _, members, users, access, org_id, owner = _service()
    viewer = _new_user(users, "v@example.com")
    members.put(org_id, viewer, "active", NOW)
    other = _new_user(users, "o@example.com")
    members.put(org_id, other, "active", NOW)
    invited = _new_user(users, "i@example.com")
    members.put(org_id, invited, "invited", NOW)

    page = service.list_members(org_id, viewer)
    assert page.viewer_role == "member"
    assert {item.user_id for item in page.items} == {owner, viewer, other}
    assert all(item.email is None for item in page.items)

    page = service.list_members(org_id, owner)
    assert page.viewer_role == "owner"
    assert {item.status for item in page.items} == {"active", "invited"}
    assert all(item.email is not None for item in page.items)

    with pytest.raises(ForbiddenError):
        service.list_members(org_id, _new_user(users, "nope@example.com"))


def test_member_events_emitted() -> None:
    service, _, members, users, _, org_id, owner = _service()
    events = service._events  # noqa: SLF001
    target = _new_user(users, "rt@example.com")
    service.invite_member(org_id, owner, "rt@example.com")
    assert (org_id, "invited", target, owner, None) in events.roster
    assert (target, "invited", org_id, None) in events.inbox
    service.accept_invitation(org_id, target)
    assert (org_id, "accepted", target, target, None) in events.roster
    assert (target, "accepted", org_id, None) in events.inbox
    service.remove_member(org_id, owner, target)
    assert (org_id, "removed", target, owner, None) in events.roster
    assert (target, "removed", org_id, None) in events.inbox


def test_list_my_memberships_inbox() -> None:
    service, orgs, members, users, access, org_id, owner = _service()
    invited = _new_user(users, "inv@example.com")
    members.put(org_id, invited, "invited", NOW)
    inbox = service.list_my_memberships(invited, status="invited")
    assert len(inbox) == 1
    assert inbox[0].org_id == org_id
    assert inbox[0].roles == []
    mine = service.list_my_memberships(owner)
    assert len(mine) == 1 and mine[0].roles == ["owner"]


def test_list_denies_non_active_admins() -> None:
    service, _, members, users, access, org_id, owner = _service()
    invited_admin = _new_user(users, "ia@example.com")
    members.put(org_id, invited_admin, "invited", NOW)
    access.assign(org_id, owner, invited_admin, "admin")
    with pytest.raises(ForbiddenError):
        service.list_members(org_id, invited_admin)

    suspended_admin = _new_user(users, "sa@example.com")
    _make_admin(members, access, org_id, suspended_admin)
    members.set_status(org_id, suspended_admin, "suspended", NOW)
    with pytest.raises(ForbiddenError):
        service.list_members(org_id, suspended_admin)

    active_admin = _new_user(users, "aa@example.com")
    _make_admin(members, access, org_id, active_admin)
    page = service.list_members(org_id, active_admin)
    assert page.viewer_role == "admin"

    members.set_status(org_id, owner, "suspended", NOW)
    page = service.list_members(org_id, owner)
    assert page.viewer_role == "owner"


def test_update_rejects_unknown_status() -> None:
    service, _, members, users, _, org_id, owner = _service()
    target = _new_user(users, "t@example.com")
    members.put(org_id, target, "active", NOW)
    with pytest.raises(InvalidMemberStateError):
        service.update_member(org_id, owner, target, status="invited")
    with pytest.raises(InvalidMemberStateError):
        service.update_member(org_id, owner, target, status="left")
    with pytest.raises(InvalidMemberStateError):
        service.update_member(org_id, owner, target, status="bogus")
    assert (
        service.update_member(org_id, owner, target, status="suspended").status
        == "suspended"
    )


def test_roster_carries_member_avatar_url() -> None:
    """Roster rows resolve the member's avatar asset to a /media/ URL."""
    media = FakeMedia()
    service, _, _, users, _, org_id, owner = _service(media=media)
    face = media.create_asset(
        _uid(), owner, "users/u/a.png", "image/png", 10, NOW, role="avatar"
    )
    users.add(
        owner, "owner@example.com", "Owner",
        avatar_media_id=face.asset_id,
    )
    row = service.list_members(org_id, owner).items[0]
    assert row.avatar_url == "/media/users/u/a.png"


def test_roster_ignores_dead_avatar_asset() -> None:
    """A dangling avatar_media_id yields null, never a broken URL."""
    service, _, _, users, _, org_id, owner = _service(media=FakeMedia())
    users.add(owner, "owner@example.com", "Owner", avatar_media_id=_uid())
    row = service.list_members(org_id, owner).items[0]
    assert row.avatar_url is None
