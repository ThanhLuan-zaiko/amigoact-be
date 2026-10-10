"""Unit tests for dual-write atomicity with batch plus compensation."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
import uuid_utils


def _uid() -> UUID:
    return UUID(str(uuid_utils.uuid7()))


NOW = datetime.now(timezone.utc)


def test_member_put_compensates_on_second_failure(monkeypatch) -> None:
    import orgs.member_repository as mod

    monkeypatch.setattr(mod, "BatchQuery", None)
    deleted: list[bool] = []

    class FakeQuery:
        def delete(self) -> None:
            deleted.append(True)

    class FakeOrgMembers:
        @staticmethod
        def create(org_id, user_id, status, joined_at, invited_by=None):  # noqa: ANN001, ANN202
            return SimpleNamespace(
                org_id=org_id,
                user_id=user_id,
                status=status,
                invited_by=invited_by,
                joined_at=joined_at,
            )

        @staticmethod
        def objects(org_id, user_id):  # noqa: ANN001, ANN202
            return FakeQuery()

    class FakeByUser:
        @staticmethod
        def create(**kwargs):  # noqa: ANN003, ANN202
            raise RuntimeError("second store offline")

    monkeypatch.setattr(mod, "OrganizationMember", FakeOrgMembers)
    monkeypatch.setattr(mod, "MemberByUser", FakeByUser)
    repo = mod.CqlMemberRepository()
    with pytest.raises(RuntimeError):
        repo.put(_uid(), _uid(), "invited", NOW)
    assert deleted == [True]


def test_member_put_uses_batch_when_available(monkeypatch) -> None:
    import orgs.member_repository as mod

    entered: list[bool] = []
    created: list[tuple] = []

    class FakeBatch:
        def __enter__(self):  # noqa: ANN202
            entered.append(True)
            return self

        def __exit__(self, *exc):  # noqa: ANN001, ANN202
            return False

    def _binder(tag: str):  # noqa: ANN202
        class Binder:
            @staticmethod
            def create(**kwargs):  # noqa: ANN003, ANN202
                created.append((tag, kwargs))
                return SimpleNamespace(**kwargs)

        return Binder()

    class FakeOrgMembers:
        @staticmethod
        def batch(batch):  # noqa: ANN001, ANN202
            assert isinstance(batch, FakeBatch)
            return _binder("org")

    class FakeByUser:
        @staticmethod
        def batch(batch):  # noqa: ANN001, ANN202
            assert isinstance(batch, FakeBatch)
            return _binder("by_user")

    monkeypatch.setattr(mod, "BatchQuery", FakeBatch)
    monkeypatch.setattr(mod, "OrganizationMember", FakeOrgMembers)
    monkeypatch.setattr(mod, "MemberByUser", FakeByUser)
    repo = mod.CqlMemberRepository()
    row = repo.put(_uid(), _uid(), "invited", NOW)
    assert entered == [True]
    assert {tag for tag, _ in created} == {"org", "by_user"}
    assert row.status == "invited"


def test_member_set_status_reverts_on_partial_failure(monkeypatch) -> None:
    import orgs.member_repository as mod

    monkeypatch.setattr(mod, "BatchQuery", None)
    reverted: list[dict] = []
    org_id, user_id = _uid(), _uid()

    class FakeOrgQuery:
        def update(self, **kwargs):  # noqa: ANN003
            pass

    class FakeOrgMembers:
        @staticmethod
        def objects(org_id, user_id):  # noqa: ANN001, ANN202
            class Query:
                def update(self, **kwargs):  # noqa: ANN003
                    if kwargs.get("status") == "suspended":
                        return None
                    reverted.append(kwargs)
                    return None

            return Query()

    class FakeByUserQuery:
        @staticmethod
        def objects(user_id, org_id):  # noqa: ANN001, ANN202
            class Query:
                def update(self, **kwargs):  # noqa: ANN003
                    raise RuntimeError("second store offline")

            return Query()

    fake_existing = SimpleNamespace(
        org_id=org_id, user_id=user_id, status="active", joined_at=NOW
    )
    monkeypatch.setattr(mod, "OrganizationMember", FakeOrgMembers)
    monkeypatch.setattr(mod, "MemberByUser", FakeByUserQuery)
    repo = mod.CqlMemberRepository()
    monkeypatch.setattr(repo, "get", lambda o, u: fake_existing)
    with pytest.raises(RuntimeError):
        repo.set_status(org_id, user_id, "suspended", NOW)
    assert reverted and reverted[0]["status"] == "active"


def test_role_assign_compensates_on_second_failure(monkeypatch) -> None:
    import rbac.repository as mod

    monkeypatch.setattr(mod, "BatchQuery", None)
    deleted: list[bool] = []

    class FakeQuery:
        def delete(self) -> None:
            deleted.append(True)

    class FakeUserRole:
        @staticmethod
        def create(**kwargs):  # noqa: ANN003, ANN202
            return SimpleNamespace(**kwargs)

        @staticmethod
        def objects(org_id, user_id, role_id):  # noqa: ANN001, ANN202
            return FakeQuery()

    class FakeByUser:
        @staticmethod
        def create(**kwargs):  # noqa: ANN003, ANN202
            raise RuntimeError("second store offline")

    monkeypatch.setattr(mod, "UserRole", FakeUserRole)
    monkeypatch.setattr(mod, "RolesByUser", FakeByUser)
    repo = mod.CqlRoleRepository()
    with pytest.raises(RuntimeError):
        repo.assign_role(_uid(), _uid(), _uid(), _uid(), NOW)
    assert deleted == [True]


def test_role_assign_uses_batch_when_available(monkeypatch) -> None:
    import rbac.repository as mod

    created: list[tuple] = []

    class FakeBatch:
        def __enter__(self):  # noqa: ANN202
            return self

        def __exit__(self, *exc):  # noqa: ANN001, ANN202
            return False

    def _binder(tag: str):  # noqa: ANN202
        class Binder:
            @staticmethod
            def create(**kwargs):  # noqa: ANN003, ANN202
                created.append((tag, kwargs))
                return SimpleNamespace(**kwargs)

        return Binder()

    class FakeUserRole:
        @staticmethod
        def batch(batch):  # noqa: ANN001, ANN202
            return _binder("user_roles")

    class FakeByUser:
        @staticmethod
        def batch(batch):  # noqa: ANN001, ANN202
            return _binder("roles_by_user")

    monkeypatch.setattr(mod, "BatchQuery", FakeBatch)
    monkeypatch.setattr(mod, "UserRole", FakeUserRole)
    monkeypatch.setattr(mod, "RolesByUser", FakeByUser)
    repo = mod.CqlRoleRepository()
    repo.assign_role(_uid(), _uid(), _uid(), _uid(), NOW)
    assert {tag for tag, _ in created} == {"user_roles", "roles_by_user"}


def test_role_revoke_uses_batch_when_available(monkeypatch) -> None:
    import rbac.repository as mod

    deleted: list[str] = []

    class FakeBatch:
        def __enter__(self):  # noqa: ANN202
            return self

        def __exit__(self, *exc):  # noqa: ANN001, ANN202
            return False

    class FakeQuery:
        def __init__(self, tag: str) -> None:
            self._tag = tag

        def batch(self, batch):  # noqa: ANN001, ANN202
            return self

        def delete(self) -> None:
            deleted.append(self._tag)

    class FakeUserRole:
        @staticmethod
        def objects(org_id, user_id, role_id):  # noqa: ANN001, ANN202
            return FakeQuery("user_roles")

    class FakeByUser:
        @staticmethod
        def objects(user_id, org_id, role_id):  # noqa: ANN001, ANN202
            return FakeQuery("roles_by_user")

    monkeypatch.setattr(mod, "BatchQuery", FakeBatch)
    monkeypatch.setattr(mod, "UserRole", FakeUserRole)
    monkeypatch.setattr(mod, "RolesByUser", FakeByUser)
    repo = mod.CqlRoleRepository()
    repo.revoke_role(_uid(), _uid(), _uid())
    assert sorted(deleted) == ["roles_by_user", "user_roles"]
