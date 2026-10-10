"""Unit tests for AuditService (org audit feed) and refresh rate limit."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from audit.service import AuditService
from core.exceptions import ForbiddenError, NotFoundError, TooManyRequestsError
from core.ids import uuid7
from rbac.interfaces import AuditReader
from tests.unit.activity_fakes import _org_with_owner
from tests.unit.hour_fakes import uid
from tests.unit.member_fakes import (
    FakeAccess,
    FakeMembers,
    FakeUsers,
)
from tests.unit.org_fakes import FakeOrgs


class FakeAuditReader(AuditReader):
    def __init__(self) -> None:
        self.rows: list = []

    def seed(self, org_id: UUID, actor_id: UUID, action: str) -> None:
        self.rows.append(
            SimpleNamespace(
                org_id=org_id,
                log_id=uuid7(),
                occurred_at=datetime.now(UTC),
                actor_id=actor_id,
                action=action,
                resource_type="member",
                resource_id=actor_id,
                result="allowed",
            )
        )

    def list_for_org(self, org_id: UUID, limit: int) -> list:
        return [
            row for row in self.rows if row.org_id == org_id
        ][:limit]


def _service() -> tuple[
    AuditService, FakeOrgs, FakeMembers, FakeAccess, FakeAuditReader, FakeUsers
]:
    orgs, members = FakeOrgs(), FakeMembers()
    access, reader, users = FakeAccess(), FakeAuditReader(), FakeUsers()
    return (
        AuditService(
            orgs=orgs,
            members=members,
            access=access,
            reader=reader,
            users=users,
        ),
        orgs,
        members,
        access,
        reader,
        users,
    )


def test_feed_returns_entries_with_actor_names() -> None:
    service, orgs, _m, _a, reader, users = _service()
    owner = uid()
    org = _org_with_owner(orgs, owner)
    users.add(owner, "owner@test.dev", "Owner Name")
    reader.seed(org.id, owner, "member.invite")
    entries = service.feed(org.id, owner)
    assert len(entries) == 1
    assert entries[0].action == "member.invite"
    assert entries[0].actor_name == "Owner Name"
    assert entries[0].result == "allowed"


def test_feed_falls_back_to_short_id_when_actor_unknown() -> None:
    service, orgs, _m, _a, reader, _u = _service()
    owner = uid()
    org = _org_with_owner(orgs, owner)
    actor = uid()
    reader.seed(org.id, actor, "activity.create")
    entries = service.feed(org.id, owner)
    assert entries[0].actor_name == str(actor)[:8]


def test_feed_allows_member_with_member_view_permission() -> None:
    service, orgs, members, access, reader, _u = _service()
    owner, viewer = uid(), uid()
    org = _org_with_owner(orgs, owner)
    members.put(org.id, viewer, "active", datetime.now(UTC))
    access.perms[(org.id, viewer)] = {"member:view"}
    reader.seed(org.id, owner, "org.update")
    entries = service.feed(org.id, viewer)
    assert len(entries) == 1


def test_feed_denies_member_without_permission() -> None:
    service, orgs, members, access, _r, _u = _service()
    owner, viewer = uid(), uid()
    org = _org_with_owner(orgs, owner)
    members.put(org.id, viewer, "active", datetime.now(UTC))
    access.perms[(org.id, viewer)] = {"member:invite"}
    with pytest.raises(ForbiddenError):
        service.feed(org.id, viewer)


def test_feed_denies_outsider() -> None:
    service, orgs, _m, _a, _r, _u = _service()
    org = _org_with_owner(orgs, uid())
    with pytest.raises(ForbiddenError):
        service.feed(org.id, uid())


def test_feed_raises_not_found_for_deleted_org() -> None:
    service, orgs, _m, _a, _r, _u = _service()
    org = _org_with_owner(orgs, uid())
    orgs.mark_deleted(org.id, datetime.now(UTC))
    with pytest.raises(NotFoundError):
        service.feed(org.id, uid())


def test_refresh_is_rate_limited() -> None:
    from tests.unit.auth_fakes import make_service

    service, parts = make_service()
    service.register(
        "a@test.dev", "0901234567", "Str0ng!Pass", "A"
    )
    pair = service.login("a@test.dev", "Str0ng!Pass", "10.0.0.1")
    parts["limiter"].hits["refresh:10.0.0.1"] = 30
    with pytest.raises(TooManyRequestsError):
        service.refresh(pair.refresh_token, "10.0.0.1")
