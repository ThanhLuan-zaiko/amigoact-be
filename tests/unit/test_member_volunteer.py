"""Unit tests for MemberService.volunteer_profile (manager view of a member)."""

from __future__ import annotations

from datetime import UTC, datetime

import uuid_utils
import pytest

from core.exceptions import ForbiddenError, MemberNotFoundError
from orgs.member_service import MemberService
from tests.unit.application_fakes import FakeApplications, FakeForms
from tests.unit.member_fakes import (
    FakeAccess,
    FakeEvents,
    FakeMembers,
    FakeOrgs,
    FakeUsers,
    NOW,
    _make_admin,
    _new_user,
    _uid,
)
from tests.unit.profile_fakes import FakeProfiles


def _svc() -> tuple[
    MemberService, FakeMembers, FakeUsers, FakeAccess,
    FakeProfiles, uuid_utils.UUID, uuid_utils.UUID,
]:
    orgs, members, users = FakeOrgs(), FakeMembers(), FakeUsers()
    access, profiles = FakeAccess(), FakeProfiles()
    org_id, owner = _uid(), _uid()
    orgs.add(org_id, owner)
    users.add(owner, "owner@example.com", "Owner")
    members.put(org_id, owner, "active", NOW)
    service = MemberService(
        orgs, members, users, access, FakeEvents(), profiles=profiles, forms=FakeForms(), applications=FakeApplications()
    )
    return service, members, users, access, profiles, org_id, owner


def _volunteer(profiles: FakeProfiles, user_id, skill_name: str, level: int) -> None:
    profiles.upsert_profile(
        user_id, "SV001", None, None, "CTK43", 2022, "Bach Khoa",
        "Hi", {"beach"}, "studying", datetime.now(UTC),
    )
    skill = profiles.add_skill(skill_name, skill_name.lower())
    profiles.user_skills.setdefault(user_id, {})[skill.id] = level
    profiles.put_contact(
        user_id, uuid_utils.uuid7(), "Mom", "mother", "0901234567", True
    )


def test_owner_reads_profile_skills_and_contacts() -> None:
    service, members, users, access, profiles, org_id, owner = _svc()
    member = _new_user(users, "vol@x.dev")
    members.put(org_id, member, "active", NOW)
    _volunteer(profiles, member, "First Aid", 4)

    view = service.volunteer_profile(org_id, member, owner)

    assert view.profile is not None and view.profile.class_name == "CTK43"
    assert [(s.name, s.level) for s in view.skills] == [("First Aid", 4)]
    assert [c.name for c in view.contacts] == ["Mom"]
    assert access.audit[-1] == ("member.volunteer.view", member, "allowed")


def test_admin_with_member_view_can_read() -> None:
    service, members, users, access, profiles, org_id, _owner = _svc()
    manager = _new_user(users, "mgr@x.dev")
    _make_admin(members, access, org_id, manager)
    member = _new_user(users, "vol2@x.dev")
    members.put(org_id, member, "active", NOW)
    _volunteer(profiles, member, "Cooking", 2)

    view = service.volunteer_profile(org_id, member, manager)

    assert view.user_id == member


def test_plain_member_is_forbidden() -> None:
    service, members, users, _access, profiles, org_id, _owner = _svc()
    peer = _new_user(users, "peer@x.dev")
    members.put(org_id, peer, "active", NOW)
    target = _new_user(users, "target@x.dev")
    members.put(org_id, target, "active", NOW)
    _volunteer(profiles, target, "Driving", 3)

    with pytest.raises(ForbiddenError):
        service.volunteer_profile(org_id, target, peer)


@pytest.mark.parametrize("status", ["invited", "left", "suspended"])
def test_non_active_target_is_not_found(status: str) -> None:
    service, members, users, _access, profiles, org_id, owner = _svc()
    target = _new_user(users, f"{status}@x.dev")
    members.put(org_id, target, status, NOW)
    _volunteer(profiles, target, "Teaching", 1)

    with pytest.raises(MemberNotFoundError):
        service.volunteer_profile(org_id, target, owner)


def test_stranger_id_is_not_found_for_owner() -> None:
    service, _m, users, _a, _p, org_id, owner = _svc()
    stranger = _new_user(users, "nobody@x.dev")

    with pytest.raises(MemberNotFoundError):
        service.volunteer_profile(org_id, stranger, owner)
