"""Unit tests for AdminService (faked ports, no DB)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from typing import Any
import uuid_utils

from types import SimpleNamespace

from admin.interfaces import ModerationStore, PlatformRoleStore
from admin.service import AdminService
from core.exceptions import (
    ForbiddenError,
    InvalidOrgStateError,
    NotFoundError,
    UserNotFoundError,
)
from notifications.interfaces import NotificationPort
from orgs.interfaces import OrgContactDetails
from rbac.catalog import PLATFORM_ADMIN_ROLE_ID
from tests.unit.member_fakes import FakeAccess, FakeUsers
from tests.unit.org_fakes import FakeMedia, FakeOrgs
from core.ids import uuid7

NOW = datetime.now(timezone.utc)
ADMIN_EMAIL = "root@amigoact.test"


def _uid() -> UUID:
    return UUID(str(uuid_utils.uuid7()))


class FakeRoles(PlatformRoleStore):
    def __init__(self) -> None:
        self.grants: set[tuple[UUID, UUID]] = set()

    def grant(self, user_id, role_id, granted_by, now):  # noqa: ANN001, ANN202
        self.grants.add((user_id, role_id))

    def revoke(self, user_id, role_id):  # noqa: ANN001, ANN202
        self.grants.discard((user_id, role_id))

    def has_role(self, user_id, role_id):  # noqa: ANN001, ANN202
        return (user_id, role_id) in self.grants

    def list_holders(self, role_id):  # noqa: ANN001, ANN202
        return [uid for uid, rid in self.grants if rid == role_id]


class FakeNotifications(NotificationPort):
    def __init__(self) -> None:
        self.sent: list[tuple] = []

    def notify(self, user_id, type, title, body="", data_json=None):  # noqa: ANN001, ANN202, A002
        self.sent.append((user_id, type, title))


def _service() -> tuple[
    AdminService, FakeOrgs, FakeRoles, FakeUsers, FakeAccess, FakeNotifications
]:
    orgs, roles, users = FakeOrgs(), FakeRoles(), FakeUsers()
    access, notes = FakeAccess(), FakeNotifications()
    service = AdminService(
        orgs=orgs,
        platform_roles=roles,
        users=users,
        notifications=notes,
        access=access,
        admin_emails=frozenset({ADMIN_EMAIL}),
    )
    return service, orgs, roles, users, access, notes


def _pending_org(orgs: FakeOrgs, owner: UUID):
    return orgs.create(
        _uid(), owner, "Biz", "biz", "", "business", "invite",
        "TAX1", "Rep", "ID1", "CEO", "pending", NOW,
        OrgContactDetails(),
    )


def test_is_admin_via_email_or_role() -> None:
    service, _, roles, *_ = _service()
    uid = _uid()
    assert service.is_admin(uid, ADMIN_EMAIL) is True
    assert service.is_admin(uid, "nobody@example.com") is False
    roles.grant(uid, PLATFORM_ADMIN_ROLE_ID, _uid(), NOW)
    assert service.is_admin(uid, "nobody@example.com") is True


def test_verify_org_moves_status_and_notifies_owner() -> None:
    service, orgs, _, users, access, notes = _service()
    owner = _uid()
    users.add(owner, "owner@example.com", "Owner")
    org = _pending_org(orgs, owner)
    admin = _uid()

    item = service.verify_org(admin, ADMIN_EMAIL, org.id)

    assert item.legal_status == "verified"
    assert item.verified_at is not None
    assert orgs.get_by_id(org.id).legal_status == "verified"
    assert notes.sent == [(owner, "organization", "T\u1ed5 ch\u1ee9c \u0111\u00e3 \u0111\u01b0\u1ee3c x\u00e1c minh")]
    assert ("org.verify", org.id, "allowed") in access.audit


def test_reject_org_records_reason_notification() -> None:
    service, orgs, _, users, _, notes = _service()
    owner = _uid()
    users.add(owner, "owner@example.com", "Owner")
    org = _pending_org(orgs, owner)

    item = service.reject_org(_uid(), ADMIN_EMAIL, org.id, "Missing papers")

    assert item.legal_status == "rejected"
    assert notes.sent[0][2] == "T\u1ed5 ch\u1ee9c ch\u01b0a \u0111\u01b0\u1ee3c x\u00e1c minh"


def test_verify_requires_admin_and_pending_state() -> None:
    service, orgs, _, users, *_ = _service()
    owner = _uid()
    users.add(owner, "owner@example.com", "Owner")
    org = _pending_org(orgs, owner)

    with pytest.raises(ForbiddenError):
        service.verify_org(_uid(), "intruder@example.com", org.id)
    service.verify_org(_uid(), ADMIN_EMAIL, org.id)
    with pytest.raises(InvalidOrgStateError):
        service.verify_org(_uid(), ADMIN_EMAIL, org.id)
    with pytest.raises(NotFoundError):
        service.verify_org(_uid(), ADMIN_EMAIL, _uid())


def test_grant_and_revoke_admin() -> None:
    service, _, roles, users, *_ = _service()
    target = _uid()
    users.add(target, "new@example.com", "Newbie")

    service.grant_admin(_uid(), ADMIN_EMAIL, target)
    assert roles.has_role(target, PLATFORM_ADMIN_ROLE_ID)
    assert service.is_admin(target, "new@example.com")

    service.revoke_admin(_uid(), ADMIN_EMAIL, target)
    assert not roles.has_role(target, PLATFORM_ADMIN_ROLE_ID)

    with pytest.raises(UserNotFoundError):
        service.grant_admin(_uid(), ADMIN_EMAIL, _uid())
    with pytest.raises(ForbiddenError):
        service.grant_admin(_uid(), "intruder@example.com", target)


class FakeModeration(ModerationStore):
    def __init__(self) -> None:
        self.rows: dict[UUID, Any] = {}

    def enqueue(self, moderation_id, asset_id, now):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            status="pending", created_at=now, moderation_id=moderation_id,
            asset_id=asset_id, reviewed_by=None, note=None,
        )
        self.rows[moderation_id] = row
        return row

    def list_by_status(self, status, limit=50):  # noqa: ANN001, ANN202
        rows = [r for r in self.rows.values() if r.status == status]
        return sorted(rows, key=lambda r: r.created_at, reverse=True)[:limit]

    def mark(self, from_status, created_at, moderation_id, to_status, reviewed_by, note, now):  # noqa: ANN001, ANN202
        row = self.rows.get(moderation_id)
        if row is None or row.status != from_status:
            return None
        row.status = to_status
        row.reviewed_by = reviewed_by
        row.note = note
        return row


def _moderation_service() -> tuple[AdminService, FakeModeration, FakeMedia]:
    orgs, roles, users = FakeOrgs(), FakeRoles(), FakeUsers()
    access, notes = FakeAccess(), FakeNotifications()
    moderation, media = FakeModeration(), FakeMedia()
    service = AdminService(
        orgs=orgs,
        platform_roles=roles,
        users=users,
        notifications=notes,
        access=access,
        admin_emails=frozenset({ADMIN_EMAIL}),
        moderation=moderation,
        media=media,
    )
    return service, moderation, media


def test_enqueue_and_review_moderation() -> None:
    service, moderation, media = _moderation_service()
    asset_id = uuid7()
    media.assets[asset_id] = SimpleNamespace(upload_status="active", file_url="/x.jpg")
    service.enqueue_moderation(asset_id)
    rows = moderation.list_by_status("pending")
    assert len(rows) == 1
    admin = uuid7()
    service.review_moderation(
        admin, ADMIN_EMAIL, "pending", rows[0].created_at,
        rows[0].moderation_id, approve=False, note="spam",
    )
    assert media.assets[asset_id].upload_status == "rejected"
    assert moderation.list_by_status("rejected")[0].note == "spam"


def test_review_requires_admin() -> None:
    service, moderation, media = _moderation_service()
    asset_id = uuid7()
    media.assets[asset_id] = SimpleNamespace(upload_status="active", file_url="/x.jpg")
    service.enqueue_moderation(asset_id)
    row = moderation.list_by_status("pending")[0]
    with pytest.raises(ForbiddenError):
        service.review_moderation(
            uuid7(), "user@example.com", "pending", row.created_at,
            row.moderation_id, approve=True, note=None,
        )
    with pytest.raises(NotFoundError):
        service.review_moderation(
            uuid7(), ADMIN_EMAIL, "pending", row.created_at,
            uuid7(), approve=True, note=None,
        )
