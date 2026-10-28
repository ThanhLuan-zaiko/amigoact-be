"""Unit tests for MemberService.match_by_skill (coordinator matching)."""

from __future__ import annotations

import uuid_utils
import pytest

from core.exceptions import ForbiddenError
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
    MemberService, FakeOrgs, FakeMembers, FakeUsers, FakeAccess,
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
    return service, orgs, members, users, access, profiles, org_id, owner


def test_match_returns_active_members_sorted() -> None:
    service, _o, members, users, _a, profiles, org_id, owner = _svc()
    skill = profiles.add_skill("First Aid", "first-aid")
    strong = _new_user(users, "a@x.dev")
    weak = _new_user(users, "b@x.dev")
    outsider = _new_user(users, "c@x.dev")
    members.put(org_id, strong, "active", NOW)
    members.put(org_id, weak, "active", NOW)
    profiles.reverse_skills[skill.id] = {
        strong: 5, weak: 2, outsider: 5,
    }
    rows = service.match_by_skill(org_id, skill.id, owner)
    assert [(m.user_id, m.level) for m in rows] == [
        (strong, 5), (weak, 2)
    ]


def test_match_filters_level_and_status() -> None:
    service, _o, members, users, _a, profiles, org_id, owner = _svc()
    skill = profiles.add_skill("CPR", "cpr")
    low = _new_user(users, "low@x.dev")
    invited = _new_user(users, "inv@x.dev")
    members.put(org_id, low, "active", NOW)
    members.put(org_id, invited, "invited", NOW)
    profiles.reverse_skills[skill.id] = {low: 2, invited: 5}
    rows = service.match_by_skill(org_id, skill.id, owner, min_level=3)
    assert rows == []
    rows = service.match_by_skill(org_id, skill.id, owner)
    assert [m.user_id for m in rows] == [low]


def test_match_requires_manager() -> None:
    service, _o, _m, users, access, profiles, org_id, _owner = _svc()
    skill = profiles.add_skill("CPR", "cpr")
    member = _new_user(users, "m@x.dev")
    with pytest.raises(ForbiddenError):
        service.match_by_skill(org_id, skill.id, member)
    assert access.audit[-1][2] == "denied"
    _make_admin(service._members, access, org_id, member)
    assert service.match_by_skill(org_id, skill.id, member) == []
