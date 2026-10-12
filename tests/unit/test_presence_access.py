"""Unit tests for MemberPresenceDirectory: only active links count."""

from __future__ import annotations

from types import SimpleNamespace

from realtime.access import MemberPresenceDirectory
from tests.unit.member_fakes import FakeMembers
from tests.unit.realtime_fakes import uid


def _members_with(org, rows: dict) -> FakeMembers:  # noqa: ANN001
    members = FakeMembers()
    for user_id, status in rows.items():
        members.rows[(org, user_id)] = SimpleNamespace(
            org_id=org, user_id=user_id, status=status
        )
    return members


def test_roster_and_orgs_skip_invited_suspended_and_left() -> None:
    org = uid()
    active, invited, suspended, left = uid(), uid(), uid(), uid()
    directory = MemberPresenceDirectory(
        _members_with(
            org,
            {
                active: "active",
                invited: "invited",
                suspended: "suspended",
                left: "left",
            },
        )
    )
    assert directory.member_ids_of(org) == [active]
    assert directory.orgs_of(active) == [org]
    for user_id in (invited, suspended, left):
        assert directory.orgs_of(user_id) == []


def test_missing_status_reads_as_active_like_is_member() -> None:
    """Legacy rows without a status may subscribe (is_member treats NULL
    as active), so presence must count them too."""
    org, legacy = uid(), uid()
    directory = MemberPresenceDirectory(_members_with(org, {legacy: None}))
    assert directory.member_ids_of(org) == [legacy]
    assert directory.orgs_of(legacy) == [org]
