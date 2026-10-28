"""Shared in-memory ports and builders for member service unit tests."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import uuid_utils

from orgs.interfaces import (
    MemberEvents,
    MemberRepository,
    OrgRepository,
    UserBrief,
    UserDirectory,
)
from orgs.member_service import MemberService
from rbac.interfaces import AccessControl
from tests.unit.application_fakes import FakeApplications, FakeForms

NOW = datetime.now(timezone.utc)


def _uid() -> UUID:
    return UUID(str(uuid_utils.uuid7()))


class FakeOrgs(OrgRepository):
    def __init__(self) -> None:
        self.orgs: dict[UUID, Any] = {}

    def add(self, org_id: UUID, owner_id: UUID, join_policy: str = "invite") -> None:
        self.orgs[org_id] = SimpleNamespace(
            id=org_id,
            owner_id=owner_id,
            join_policy=join_policy,
            deleted_at=None,
            name=f"Org {str(org_id)[:4]}",
            slug=str(org_id)[:8],
        )

    def create(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        raise NotImplementedError

    def get_by_id(self, org_id):  # noqa: ANN001, ANN202
        return self.orgs.get(org_id)

    def get_by_slug(self, slug):  # noqa: ANN001, ANN202
        return None

    def list_by_user(self, user_id):  # noqa: ANN001, ANN202
        return []

    def count_members(self, org_id):  # noqa: ANN001, ANN202
        return 0

    def is_member(self, org_id, user_id):  # noqa: ANN001, ANN202
        return False

    def update_details(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        raise NotImplementedError

    def mark_deleted(self, org_id, now):  # noqa: ANN001, ANN202
        return None

    def mark_restored(self, org_id, now):  # noqa: ANN001, ANN202
        return None

    def set_brand_media(self, org_id, role, asset_id, now):  # noqa: ANN001, ANN202
        org = self.orgs.get(org_id)
        if org is not None:
            setattr(org, f"{role}_media_id", asset_id)

    def list_by_legal_status(self, legal_status, limit=100):  # noqa: ANN001, ANN202
        return []

    def list_public(self):  # noqa: ANN001, ANN202
        return []

    def set_legal_status(self, org_id, legal_status, verified_at, verified_by, now):  # noqa: ANN001, ANN202
        return None

    def delete_everything(self, org_id):  # noqa: ANN001, ANN202
        return False


class FakeMembers(MemberRepository):
    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, UUID], Any] = {}

    def get(self, org_id, user_id):  # noqa: ANN001, ANN202
        return self.rows.get((org_id, user_id))

    def list_by_org(self, org_id):  # noqa: ANN001, ANN202
        return [row for row in self.rows.values() if row.org_id == org_id]

    def list_links_by_user(self, user_id):  # noqa: ANN001, ANN202
        return [row for row in self.rows.values() if row.user_id == user_id]

    def put(self, org_id, user_id, status, now, invited_by=None):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            org_id=org_id,
            user_id=user_id,
            status=status,
            invited_by=invited_by,
            joined_at=now,
        )
        self.rows[(org_id, user_id)] = row
        return row

    def set_status(self, org_id, user_id, status, now, invited_by=None):  # noqa: ANN001, ANN202
        row = self.rows.get((org_id, user_id))
        if row is None:
            return None
        row.status = status
        row.joined_at = now
        if invited_by is not None:
            row.invited_by = invited_by
        return row


class FakeUsers(UserDirectory):
    def __init__(self) -> None:
        self.users: dict[UUID, UserBrief] = {}

    def add(
        self,
        user_id: UUID,
        email: str,
        name: str = "User",
        status: str = "active",
        avatar_media_id: UUID | None = None,
    ) -> None:
        self.users[user_id] = UserBrief(
            id=user_id,
            full_name=name,
            email=email,
            status=status,
            avatar_media_id=avatar_media_id,
        )

    def get_brief(self, user_id):  # noqa: ANN001, ANN202
        return self.users.get(user_id)

    def find_by_email(self, email):  # noqa: ANN001, ANN202
        for user in self.users.values():
            if user.email == email:
                return user
        return None


_ADMIN_PERMS = {
    "member:invite",
    "member:suspend",
    "member:remove",
    "member:view",
    "activity:view",
    "activity:create",
    "activity:manage",
}


class FakeAccess(AccessControl):
    def __init__(self) -> None:
        self.perms: dict[tuple[UUID, UUID], set[str]] = {}
        self.roles: dict[tuple[UUID, UUID], set[str]] = {}
        # Custom role name -> permission set, per org. Tests register
        # role bundles here before exercising assign/update paths.
        self.role_perms: dict[tuple[UUID, str], set[str]] = {}
        self.audit: list[tuple] = []

    def has_permission(self, org_id, user_id, permission):  # noqa: ANN001, ANN202
        return permission in self.perms.get((org_id, user_id), set())

    def effective_permissions(self, org_id, user_id):  # noqa: ANN001, ANN202
        return set(self.perms.get((org_id, user_id), set()))

    def role_permissions_of(self, org_id, role_name):  # noqa: ANN001, ANN202
        if role_name == "admin":
            return set(_ADMIN_PERMS)
        value = self.role_perms.get((org_id, role_name))
        return None if value is None else set(value)

    def role_names_of(self, org_id, user_id):  # noqa: ANN001, ANN202
        return sorted(self.roles.get((org_id, user_id), set()))

    def role_map(self, org_id):  # noqa: ANN001, ANN202
        out: dict[UUID, list[str]] = {}
        for (oid, uid), names in self.roles.items():
            if oid == org_id:
                out[uid] = sorted(names)
        return out

    def _role_perms(self, org_id, role_name):  # noqa: ANN001, ANN202
        return _ADMIN_PERMS if role_name == "admin" else self.role_perms.get(
            (org_id, role_name), set()
        )

    def assign(self, org_id, actor_id, user_id, role_name):  # noqa: ANN001, ANN202
        self.roles.setdefault((org_id, user_id), set()).add(role_name)
        self.perms.setdefault((org_id, user_id), set()).update(
            self._role_perms(org_id, role_name)
        )

    def revoke(self, org_id, user_id, role_name):  # noqa: ANN001, ANN202
        self.roles.get((org_id, user_id), set()).discard(role_name)
        self.perms.get((org_id, user_id), set()).difference_update(
            self._role_perms(org_id, role_name)
        )

    def record(self, org_id, actor_id, action, resource_type, resource_id, result, metadata=None):  # noqa: ANN001, ANN202
        self.audit.append((action, resource_id, result))


class FakeEvents(MemberEvents):
    def __init__(self) -> None:
        self.roster: list[tuple] = []
        self.inbox: list[tuple] = []

    def member_changed(self, org_id, action, target_id, actor_id, detail=None):  # noqa: ANN001, ANN202
        self.roster.append((org_id, action, target_id, actor_id, detail))

    def inbox_changed(self, user_id, action, org_id, detail=None):  # noqa: ANN001, ANN202
        self.inbox.append((user_id, action, org_id, detail))


def _service(
    join_policy: str = "invite",
    media=None,  # noqa: ANN001
) -> tuple[MemberService, FakeOrgs, FakeMembers, FakeUsers, FakeAccess, UUID, UUID]:
    orgs, members, users, access = FakeOrgs(), FakeMembers(), FakeUsers(), FakeAccess()
    org_id, owner = _uid(), _uid()
    orgs.add(org_id, owner, join_policy=join_policy)
    users.add(owner, "owner@example.com", "Owner")
    members.put(org_id, owner, "active", NOW)
    service = MemberService(
        orgs, members, users, access, FakeEvents(), media=media,
        forms=FakeForms(), applications=FakeApplications(),
    )
    return service, orgs, members, users, access, org_id, owner


def _new_user(users: FakeUsers, email: str, status: str = "active") -> UUID:
    uid = _uid()
    users.add(uid, email, f"Name {email}", status=status)
    return uid


def _make_admin(
    members: FakeMembers, access: FakeAccess, org_id: UUID, user_id: UUID
) -> None:
    members.put(org_id, user_id, "active", NOW)
    access.assign(org_id, _uid(), user_id, "admin")
