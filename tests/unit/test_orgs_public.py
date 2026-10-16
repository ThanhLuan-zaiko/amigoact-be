"""Unit tests for PublicOrgService with fake ports (no I/O, fast)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.exceptions import NotFoundError
from core.ids import uuid7
from orgs.interfaces import (
    OrgActivityBrief,
    OrgActivityListing,
    OrgContactDetails,
)
from orgs.public_service import PublicOrgService
from orgs.service import OrgService
from tests.unit.member_fakes import FakeUsers
from tests.unit.org_fakes import (
    FakeActivityDirectory,
    FakeDirectoryEvents,
    FakeMedia,
    FakeOrgs,
    new_owner,
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


def test_public_listing_carries_owner_brief() -> None:
    orgs, media, users = FakeOrgs(), FakeMedia(), FakeUsers()
    service = OrgService(orgs)
    public = PublicOrgService(orgs, media, users=users)
    owner = new_owner()
    avatar = media.create_asset(
        uuid7(), owner, "users/o/a.png", "image/png", 10,
        datetime.now(timezone.utc), role="avatar",
    )
    users.add(
        owner, "o@x.com", "Owner Name", avatar_media_id=avatar.asset_id
    )
    service.create_org(owner, "Pic", "pic-own", "", "club")

    item = public.list_public_orgs().items[0]
    assert item.owner_name == "Owner Name"
    assert item.owner_avatar_url == "/media/users/o/a.png"
    assert not hasattr(item, "owner_id")


def test_public_listing_owner_fields_none_without_directory() -> None:
    orgs = FakeOrgs()
    service = OrgService(orgs)
    public = PublicOrgService(orgs)
    service.create_org(new_owner(), "Solo", "solo-pub", "", "club")
    item = public.list_public_orgs().items[0]
    assert item.owner_name is None
    assert item.owner_avatar_url is None
    assert item.media == []
    assert item.media_count == 0


def test_public_listing_carries_media_preview() -> None:
    """Card media: cover first, then gallery; logo/attachment stay out."""
    orgs, media = FakeOrgs(), FakeMedia()
    service = OrgService(orgs)
    public = PublicOrgService(orgs, media)
    owner = new_owner()
    org = service.create_org(owner, "Show", "show-pub", "", "club")
    now = datetime.now(timezone.utc)
    media.create_asset(uuid7(), org.id, "o/clip.mp4", "video/mp4", 1, now)
    media.create_asset(
        uuid7(), org.id, "o/cover.png", "image/png", 1, now, role="cover"
    )
    media.create_asset(
        uuid7(), org.id, "o/logo.png", "image/png", 1, now, role="logo"
    )
    media.create_asset(
        uuid7(), org.id, "o/post.png", "image/png", 1, now, role="attachment"
    )

    item = public.list_public_orgs().items[0]
    assert [m.url for m in item.media] == [
        "/media/o/cover.png",
        "/media/o/clip.mp4",
    ]
    assert item.media[0].kind == "image"
    assert item.media[1].kind == "video"
    assert item.media_count == 2


def test_public_media_list_keeps_videos_and_beats_preview_cap() -> None:
    """The lightbox list: cover-first, videos included, no tile cap;
    logo/attachment/dead assets still stay off the public surface."""
    orgs, media = FakeOrgs(), FakeMedia()
    service = OrgService(orgs)
    public = PublicOrgService(orgs, media)
    owner = new_owner()
    org = service.create_org(owner, "Full", "full-pub", "", "club")
    now = datetime.now(timezone.utc)
    media.create_asset(
        uuid7(), org.id, "o/cover.png", "image/png", 1, now, role="cover"
    )
    media.create_asset(
        uuid7(), org.id, "o/logo.png", "image/png", 1, now, role="logo"
    )
    media.create_asset(
        uuid7(), org.id, "o/post.png", "image/png", 1, now,
        role="attachment",
    )
    for index in range(9):
        media.create_asset(
            uuid7(), org.id, f"o/{index}.png", "image/png", 1, now
        )
    media.create_asset(uuid7(), org.id, "o/clip.mp4", "video/mp4", 1, now)
    dead = media.create_asset(uuid7(), org.id, "o/dead.png", "image/png", 1, now)
    media.delete_asset(dead.asset_id)

    items = public.list_public_media("full-pub")
    assert items[0].url == "/media/o/cover.png"
    urls = [item.url for item in items]
    assert "/media/o/clip.mp4" in urls
    assert "/media/o/dead.png" not in urls
    assert len(items) == 11  # cover + 9 gallery images + the video
    assert sum(1 for item in items if item.kind == "video") == 1


def test_public_media_list_404s_for_missing_and_dead_orgs() -> None:
    orgs, media = FakeOrgs(), FakeMedia()
    service = OrgService(orgs)
    public = PublicOrgService(orgs, media)
    owner = new_owner()
    org = service.create_org(owner, "Gone", "gone-pub", "", "club")
    with pytest.raises(NotFoundError):
        public.list_public_media("missing")
    service.soft_delete_org(org.id, owner)
    with pytest.raises(NotFoundError):
        public.list_public_media("gone-pub")


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
