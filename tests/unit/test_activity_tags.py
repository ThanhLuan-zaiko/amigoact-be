"""Unit tests: tag_slug, TagService, and tag flow in ActivityService."""

from __future__ import annotations

import pytest
import uuid_utils

from activities.category_service import CategoryService
from activities.model import tag_slug
from activities.service import ActivityService
from activities.tag_service import TagService
from tests.unit.activity_fakes import (
    FakeAccess,
    FakeActivities,
    FakeCategories,
    FakeOrgs,
    FakeTags,
    _fields,
    _org_with_owner,
)
from core.exceptions import InvalidOrgStateError


def _service():
    activities = FakeActivities()
    tags = FakeTags()
    orgs = FakeOrgs()
    access = FakeAccess()
    owner = uuid_utils.uuid7()
    service = ActivityService(
        activities=activities,
        categories=FakeCategories(),
        orgs=orgs,
        access=access,
        tags=TagService(tags),
    )
    return service, tags, activities, orgs, owner


class TestTagSlug:
    def test_vietnamese_and_punctuation(self) -> None:
        assert tag_slug("Môi trường!") == "moi-truong"
        assert tag_slug("  Đà Nẵng  ") == "da-nang"
        assert tag_slug("Trẻ em 2025") == "tre-em-2025"

    def test_invalid_names_collapse_to_empty(self) -> None:
        assert tag_slug("!!!") == ""
        assert tag_slug("   ") == ""


class TestEnsure:
    def test_creates_and_dedupes_by_slug(self) -> None:
        _, tags, _, _, _ = _service()
        svc = TagService(tags)
        first = svc.ensure(["Môi trường", "moi truong", "Y tế"])
        assert first == ["Môi trường", "Y tế"]
        assert set(tags.rows) == {"moi-truong", "y-te"}
        # Second writer gets the canonical first-seen name back.
        assert svc.ensure(["môi TRƯỜNG"]) == ["Môi trường"]
        assert tags.rows["moi-truong"].name == "Môi trường"

    def test_drops_invalid_and_caps_at_ten(self) -> None:
        _, tags, _, _, _ = _service()
        svc = TagService(tags)
        names = svc.ensure(
            ["!!!", ""] + [f"tag {i}" for i in range(15)]
            + ["x" * 60]
        )
        assert names == [f"tag {i}" for i in range(10)]

    def test_search_matches_name_and_slug(self) -> None:
        _, tags, _, _, _ = _service()
        svc = TagService(tags)
        svc.ensure(["Môi trường", "Hiến máu"])
        assert [s.slug for s in svc.search("moi")] == ["moi-truong"]
        assert [s.slug for s in svc.search("Hiến")] == ["hien-mau"]
        assert {s.slug for s in svc.search("")} == {
            "moi-truong",
            "hien-mau",
        }


class TestActivityTagFlow:
    def test_create_stores_canonical_names(self) -> None:
        service, tags, _, orgs, owner = _service()
        org = _org_with_owner(orgs, owner, "tagclub")
        row = service.create_activity(
            org.id,
            owner,
            _fields(service, tag_names=["Môi trường", "moi truong"]),
        )
        assert row.tag_names == ["Môi trường"]
        assert set(tags.rows) == {"moi-truong"}

    def test_update_recatalogs_names(self) -> None:
        service, tags, activities, orgs, owner = _service()
        org = _org_with_owner(orgs, owner, "tagclub2")
        row = service.create_activity(
            org.id, owner, _fields(service, tag_names=["Sách cũ"])
        )
        updated = service.update_activity(
            org.id,
            row.id,
            owner,
            _fields(service, tag_names=["Hiến máu", "  "]),
        )
        assert updated.tag_names == ["Hiến máu"]
        assert set(tags.rows) == {"sach-cu", "hien-mau"}

    def test_public_tag_feed_hides_drafts(self) -> None:
        service, _, activities, orgs, owner = _service()
        org = _org_with_owner(orgs, owner, "tagclub3")
        draft = service.create_activity(
            org.id, owner, _fields(service, tag_names=["Biển xanh"])
        )
        pub = service.create_activity(
            org.id,
            owner,
            _fields(
                service, slug="other-slug", tag_names=["Biển xanh"]
            ),
        )
        service.set_status(org.id, pub.id, owner, "published")
        rows = service.list_public(tag_slug="bien-xanh")
        assert [r.id for r in rows] == [pub.id]
        # The raw name also resolves through the normalizer.
        rows2 = service.list_public(tag_slug="Biển xanh!")
        assert [r.id for r in rows2] == [pub.id]

    def test_tag_feed_intersects_category(self) -> None:
        service, _, _, orgs, owner = _service()
        org = _org_with_owner(orgs, owner, "tagclub4")
        cat = CategoryService(
            categories=service._categories, orgs=orgs, access=service._access
        ).create_category(
            org.id, owner, "Eco", "eco", None, None, None, None
        )
        hit = service.create_activity(
            org.id,
            owner,
            _fields(service, tag_names=["Rừng"], category_id=cat.id),
        )
        miss = service.create_activity(
            org.id,
            owner,
            _fields(service, slug="s2", tag_names=["Rừng"]),
        )
        for row in (hit, miss):
            service.set_status(org.id, row.id, owner, "published")
        rows = service.list_public(
            tag_slug="rung", category_id=cat.id
        )
        assert [r.id for r in rows] == [hit.id]

    def test_non_public_status_filter_still_guards(self) -> None:
        service, _, _, _, _ = _service()
        with pytest.raises(InvalidOrgStateError):
            service.list_public(status="draft")
