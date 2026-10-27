"""Org baseline permissions and the role ceiling in AccessControlService."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from rbac.interfaces import MemberDefaultsRepository
from rbac.service import AccessControlService
from tests.unit.member_fakes import NOW, FakeMembers
from tests.unit.test_access_control import FakeAudit, FakeGrants, FakeRoles, _uid


class FakeDefaults(MemberDefaultsRepository):
    def __init__(self) -> None:
        self.rows: dict[UUID, set[str]] = {}

    def list_defaults(self, org_id):  # noqa: ANN001, ANN202
        return set(self.rows.get(org_id, set()))

    def set_defaults(self, org_id, codes):  # noqa: ANN001, ANN202
        self.rows[org_id] = set(codes)


def _world():  # noqa: ANN202
    roles, defaults, members = FakeRoles(), FakeDefaults(), FakeMembers()
    service = AccessControlService(
        roles, FakeGrants(), FakeAudit(), defaults=defaults, members=members
    )
    return service, roles, defaults, members, _uid()


def test_baseline_applies_to_active_members_only() -> None:
    service, _, defaults, members, org = _world()
    active, invited, stranger = _uid(), _uid(), _uid()
    members.put(org, active, "active", NOW)
    members.put(org, invited, "invited", NOW)
    assert service.has_permission(org, active, "member:invite") is False
    defaults.set_defaults(org, {"member:invite"})
    assert service.has_permission(org, active, "member:invite") is True
    assert service.has_permission(org, invited, "member:invite") is False
    assert service.has_permission(org, stranger, "member:invite") is False
    assert service.has_permission(org, active, "member:remove") is False
    assert "member:invite" in service.effective_permissions(org, active)
    assert service.effective_permissions(org, stranger) == set()


def _custom(roles: FakeRoles, org: UUID, user: UUID, name: str, position: int) -> None:
    role_id = _uid()
    roles.roles[role_id] = SimpleNamespace(
        id=role_id, org_id=org, name=name, description="",
        is_system=False, position=position,
    )
    roles.by_name[(org, name)] = role_id
    roles.assignments.append(
        SimpleNamespace(
            org_id=org, user_id=user, role_id=role_id,
            granted_at=datetime.now(timezone.utc), expires_at=None,
        )
    )


def test_role_ceiling_is_the_top_ranked_custom_role() -> None:
    service, roles, _, _, org = _world()
    user = _uid()
    assert service.role_ceiling(org, user) is None
    _custom(roles, org, user, "Low", 1)
    _custom(roles, org, user, "High", 7)
    assert service.role_ceiling(org, user) == 7
    assert service.role_position_of(org, "Low") == 1
    assert service.role_position_of(org, "ghost") is None
