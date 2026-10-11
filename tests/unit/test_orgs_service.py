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
from core.ids import uuid7
from orgs.interfaces import (
    OrgActivityBrief,
    OrgActivityListing,
    OrgContactDetails,
)
from orgs.public_service import PublicOrgService
from orgs.service import OrgService
from tests.unit.org_fakes import (
    FakeActivityDirectory,
    FakeDirectoryEvents,
    FakeMedia,
    FakeOrgs,
    new_owner,
)


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


def test_public_listing_hides_trashed_orgs_until_restore() -> None:
    orgs = FakeOrgs()
    service, public = OrgService(orgs), PublicOrgService(orgs)
    owner = new_owner()
    live = service.create_org(owner, "Live", "live-1", "", "club")
    trashed = service.create_org(owner, "Gone", "gone-1", "", "group")
    service.soft_delete_org(trashed.id, owner)

    assert [o.slug for o in public.list_public_orgs().items] == ["live-1"]

    service.restore_org(trashed.id, owner)
    slugs = [o.slug for o in public.list_public_orgs().items]
    assert set(slugs) == {"live-1", "gone-1"}
    assert live.id is not None


def test_public_listing_never_leaks_private_fields() -> None:
    orgs = FakeOrgs()
    service, public = OrgService(orgs), PublicOrgService(orgs)
    owner = new_owner()
    service.create_org(
        owner, "Biz", "biz-pub", "", "business",
        tax_code="0312345678", legal_rep_name="Nguyen Van A",
        legal_rep_id="012345678901", legal_rep_position="Giam doc",
        contact=OrgContactDetails(email="boss@biz.vn", phone="0901234567"),
    )
    item = public.list_public_orgs().items[0]
    for private in (
        "tax_code", "legal_rep_id", "owner_id", "email", "phone",
        "legal_status",
    ):
        assert not hasattr(item, private)


def test_public_snapshot_resolves_brand_media_urls() -> None:
    orgs, media = FakeOrgs(), FakeMedia()
    service = OrgService(orgs)
    public = PublicOrgService(orgs, media)
    owner = new_owner()
    org = service.create_org(owner, "Pic", "pic-1", "", "club")
    logo = media.create_asset(
        uuid7(), org.id, "orgs/pic-1/logo.png", "image/png", 10,
        datetime.now(timezone.utc), role="logo",
    )
    orgs.set_brand_media(org.id, "logo", logo.asset_id, datetime.now(timezone.utc))

    item = public.list_public_orgs().items[0]
    assert item.logo_url == f"/media/{logo.file_url}"
    assert item.cover_url is None


def test_public_detail_exposes_trust_signals_not_pii() -> None:
    orgs, media = FakeOrgs(), FakeMedia()
    service = OrgService(orgs)
    public = PublicOrgService(orgs, media)
    owner = new_owner()
    service.create_org(
        owner, "Biz", "biz-pub", "", "business",
        tax_code="0312345678", legal_rep_name="Nguyen Van A",
        legal_rep_id="012345678901", legal_rep_position="Giam doc",
        contact=OrgContactDetails(
            email="boss@biz.vn", phone="0901234567",
            website="biz.vn", city="Da Nang",
            legal_name="CT Biz", license_number="LN-1",
        ),
    )
    detail = public.get_public_org("biz-pub")
    assert detail.member_count == 1
    assert detail.email == "boss@biz.vn"
    assert detail.tax_code == "0312345678"
    assert detail.legal_status == "pending"
    assert detail.legal_name == "CT Biz"
    for pii in (
        "legal_rep_id", "legal_rep_name", "legal_rep_position",
        "owner_id", "previous_slug", "deleted_at",
    ):
        assert not hasattr(detail, pii)


def test_public_detail_404s_for_missing_trashed_and_inactive() -> None:
    orgs = FakeOrgs()
    service, public = OrgService(orgs), PublicOrgService(orgs)
    owner = new_owner()
    gone = service.create_org(owner, "Gone", "gone-pub", "", "club")
    service.create_org(owner, "Idle", "idle-pub", "", "club")
    orgs.orgs[gone.id].status = "suspended"
    with pytest.raises(NotFoundError):
        public.get_public_org("missing")
    with pytest.raises(NotFoundError):
        public.get_public_org("gone-pub")
    service.soft_delete_org(gone.id, owner)
    with pytest.raises(NotFoundError):
        public.get_public_org("gone-pub")


def test_public_detail_gallery_keeps_only_live_gallery_images() -> None:
    orgs, media = FakeOrgs(), FakeMedia()
    service = OrgService(orgs)
    public = PublicOrgService(orgs, media)
    owner = new_owner()
    org = service.create_org(owner, "Gal", "gal-pub", "", "club")
    now = datetime.now(timezone.utc)
    media.create_asset(uuid7(), org.id, "o/1.png", "image/png", 1, now)
    media.create_asset(uuid7(), org.id, "o/2.png", "image/png", 1, now)
    media.create_asset(
        uuid7(), org.id, "o/logo.png", "image/png", 1, now, role="logo"
    )
    media.create_asset(uuid7(), org.id, "o/clip.mp4", "video/mp4", 1, now)
    detail = public.get_public_org("gal-pub")
    assert detail.gallery == ["/media/o/1.png", "/media/o/2.png"]


def test_public_detail_merges_activity_listing() -> None:
    orgs, acts = FakeOrgs(), FakeActivityDirectory()
    service = OrgService(orgs)
    public = PublicOrgService(orgs, activities=acts)
    owner = new_owner()
    org = service.create_org(owner, "Busy", "busy-pub", "", "club")
    now = datetime.now(timezone.utc)
    brief = OrgActivityBrief(
        id=uuid7(), slug="run", title="Run", status="published",
        city="Hue", start_at=now,
    )
    acts.listings[org.id] = OrgActivityListing(total=3, items=[brief])
    detail = public.get_public_org("busy-pub")
    assert detail.activity_count == 3
    assert [a.slug for a in detail.activities] == ["run"]

    quiet_orgs = FakeOrgs()
    OrgService(quiet_orgs).create_org(owner, "Quiet", "quiet-pub", "", "club")
    detail = PublicOrgService(quiet_orgs).get_public_org("quiet-pub")
    assert detail.activity_count == 0
    assert detail.activities == []


def test_mutations_emit_public_directory_events() -> None:
    orgs, events = FakeOrgs(), FakeDirectoryEvents()
    service = OrgService(orgs, events=events)
    owner = new_owner()
    org = service.create_org(owner, "Live", "evt-1", "", "club")
    service.update_org(org.id, owner, "Live 2", "")
    service.soft_delete_org(org.id, owner)
    service.restore_org(org.id, owner)
    service.hard_delete_org(org.id, owner)
    assert events.calls == [
        ("created", org.id, "evt-1"),
        ("updated", org.id, "evt-1"),
        ("removed", org.id, "evt-1"),
        ("restored", org.id, "evt-1"),
        ("removed", org.id, "evt-1"),
    ]


def test_mutations_without_events_port_stay_silent() -> None:
    service = OrgService(FakeOrgs())
    owner = new_owner()
    org = service.create_org(owner, "Solo", "solo-1", "", "club")
    service.soft_delete_org(org.id, owner)  # no events port: no crash
