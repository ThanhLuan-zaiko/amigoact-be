"""Unit tests for OrgService with a fake repository (no I/O, fast)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.exceptions import (
    ForbiddenError,
    InvalidBusinessProfileError,
    NotFoundError,
    OrgDeletedError,
    SlugTakenError,
)
from orgs.interfaces import OrgContactDetails
from orgs.service import OrgService
from tests.unit.org_fakes import FakeOrgs, new_owner


def test_create_club_without_legal_identity() -> None:
    service = OrgService(FakeOrgs())
    snapshot = service.create_org(new_owner(), "Club A", "club-a", "", "club")
    assert snapshot.legal_status == "none"
    assert snapshot.member_count == 1


def test_create_business_requires_legal_head() -> None:
    service = OrgService(FakeOrgs())
    with pytest.raises(InvalidBusinessProfileError):
        service.create_org(new_owner(), "Biz", "biz-1", "", "business")
    snapshot = service.create_org(
        new_owner(), "Biz", "biz-1", "", "business",
        tax_code="0312345678", legal_rep_name="Nguyen Van A",
        legal_rep_id="012345678901", legal_rep_position="Giam doc",
    )
    assert snapshot.legal_status == "pending"
    assert snapshot.tax_code == "0312345678"


def test_duplicate_slug_rejected() -> None:
    service = OrgService(FakeOrgs())
    owner = new_owner()
    service.create_org(owner, "Club A", "club-a", "", "club")
    with pytest.raises(SlugTakenError):
        service.create_org(owner, "Club B", "club-a", "", "group")


def test_list_mine_returns_only_owner_orgs() -> None:
    repo = FakeOrgs()
    service = OrgService(repo)
    mine, other = new_owner(), new_owner()
    service.create_org(mine, "Mine", "mine-1", "", "group")
    service.create_org(other, "Other", "other-1", "", "group")
    assert [o.slug for o in service.list_my_orgs(mine).items] == ["mine-1"]
    assert isinstance(datetime.now(timezone.utc), datetime)


def test_update_soft_restore_hard_cycle() -> None:
    service = OrgService(FakeOrgs())
    owner, stranger = new_owner(), new_owner()
    created = service.create_org(owner, "Club A", "club-a", "Old", "club")

    renamed = service.update_org(created.id, owner, "Club B", "New")
    assert renamed.name == "Club B"
    with pytest.raises(ForbiddenError):
        service.update_org(created.id, stranger, "Hijack", "")

    trashed = service.soft_delete_org(created.id, owner)
    assert trashed.deleted_at is not None
    assert service.list_my_orgs(owner).items == []
    assert [o.slug for o in service.list_my_orgs(owner, include_deleted=True).items] == ["club-a"]
    with pytest.raises(OrgDeletedError):
        service.update_org(created.id, owner, "Again", "")

    restored = service.restore_org(created.id, owner)
    assert restored.deleted_at is None
    assert [o.slug for o in service.list_my_orgs(owner).items] == ["club-a"]

    with pytest.raises(ForbiddenError):
        service.hard_delete_org(created.id, stranger)
    assert service.hard_delete_org(created.id, owner) == 0
    with pytest.raises(NotFoundError):
        service.update_org(created.id, owner, "Ghost", "")


def test_restore_live_org_rejected() -> None:
    service = OrgService(FakeOrgs())
    owner = new_owner()
    created = service.create_org(owner, "Club A", "club-a", "", "club")
    with pytest.raises(InvalidBusinessProfileError):
        service.restore_org(created.id, owner)


def test_create_org_with_contact_details() -> None:
    service = OrgService(FakeOrgs())
    snapshot = service.create_org(
        new_owner(),
        "Club A",
        "club-a",
        "",
        "club",
        contact=OrgContactDetails(
            email="hello@club.vn", city="Da Nang", is_personal=True
        ),
    )
    assert snapshot.email == "hello@club.vn"
    assert snapshot.city == "Da Nang"
    assert snapshot.is_personal is True


def test_update_org_replaces_contact_details() -> None:
    service = OrgService(FakeOrgs())
    owner = new_owner()
    org = service.create_org(
        owner, "Club A", "club-a", "", "club",
        contact=OrgContactDetails(email="a@club.vn", city="Hue"),
    )
    updated = service.update_org(
        org.id,
        owner,
        "Club A",
        "",
        contact=OrgContactDetails(email="b@club.vn"),
    )
    assert updated.email == "b@club.vn"
    # Omitted contact fields clear under the full-replace contract.
    assert updated.city is None

    with pytest.raises(InvalidBusinessProfileError):
        service.update_org(
            org.id, owner, "Club A", "",
            contact=OrgContactDetails(email="x" * 300),
        )
