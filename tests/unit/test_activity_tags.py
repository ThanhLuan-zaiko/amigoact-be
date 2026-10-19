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
    _fields,
    _org_with_owner,
)
from tests.unit.tag_fakes import FakeOrgTags
from core.exceptions import InvalidOrgStateError


def _service():
    activities = FakeActivities()
    tags = FakeOrgTags(activities)
    orgs = FakeOrgs()
    access = FakeAccess()
    owner = uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner, "tag-org")
    service = ActivityService(
        activities=activities,
        categories=FakeCategories(),
        orgs=orgs,
        access=access,
        tags=TagService(tags),
    )
    return service, tags, activities, orgs, org, owner


class TestTagSlug:
    def test_vietnamese_and_punctuation(self) -> None:
        assert tag_slug("M\u00f4i tr\u01b0\u1eddng!") == "moi-truong"
        assert tag_slug("  \u0110\u00e0 N\u1eb5ng  ") == "da-nang"
        assert tag_slug("Tr\u1ebb em 2025") == "tre-em-2025"

    def test_invalid_names_collapse_to_empty(self) -> None:
        assert tag_slug("!!!") == ""
        assert tag_slug("   ") == ""


class TestEnsure:
    def test_creates_and_dedupes_by_slug(self) -> None:
        _, tags, _, _, org, _ = _service()
        svc = TagService(tags)
        first = svc.ensure(
            org.id, ["M\u00f4i tr\u01b0\u1eddng", "moi truong", "Y t\u1ebf"]
        )
        assert first == ["M\u00f4i tr\u01b0\u1eddng", "Y t\u1ebf"]
        assert {slug for _, slug in tags.rows} == {"moi-truong", "y-te"}
        # Second writer gets the org's canonical first-seen name back.
        assert svc.ensure(org.id, ["m\u00f4i TR\u01af\u1edcNG"]) == [
            "M\u00f4i tr\u01b0\u1eddng"
        ]
        assert tags.rows[(org.id, "moi-truong")].name == (
            "M\u00f4i tr\u01b0\u1eddng"
        )

    def test_each_org_keeps_its_own_spelling(self) -> None:
        _, tags, _, orgs, org, owner = _service()
        other = _org_with_owner(orgs, uuid_utils.uuid7(), "tag-org-b")
        svc = TagService(tags)
        assert svc.ensure(org.id, ["M\u00f4i tr\u01b0\u1eddng"]) == [
            "M\u00f4i tr\u01b0\u1eddng"
        ]
        assert svc.ensure(other.id, ["moi truong"]) == ["moi truong"]
        assert tags.rows[(org.id, "moi-truong")].name == (
            "M\u00f4i tr\u01b0\u1eddng"
        )
        assert tags.rows[(other.id, "moi-truong")].name == "moi truong"

    def test_drops_invalid_and_caps_at_ten(self) -> None:
        _, tags, _, _, org, _ = _service()
        svc = TagService(tags)
        names = svc.ensure(
            org.id,
            ["!!!", ""] + [f"tag {i}" for i in range(15)]
            + ["x" * 60],
        )
        assert names == [f"tag {i}" for i in range(10)]


class TestActivityTagFlow:
    def test_create_stores_canonical_names(self) -> None:
        service, tags, _, _, org, owner = _service()
        row = service.create_activity(
            org.id,
            owner,
            _fields(
                service,
                tag_names=["M\u00f4i tr\u01b0\u1eddng", "moi truong"],
            ),
        )
        assert row.tag_names == ["M\u00f4i tr\u01b0\u1eddng"]
        assert {slug for _, slug in tags.rows} == {"moi-truong"}

    def test_update_recatalogs_names(self) -> None:
        service, tags, _, _, org, owner = _service()
        row = service.create_activity(
            org.id, owner, _fields(service, tag_names=["S\u00e1ch c\u0169"])
        )
        updated = service.update_activity(
            org.id,
            row.id,
            owner,
            _fields(service, tag_names=["Hi\u1ebfn m\u00e1u", "  "]),
        )
        assert updated.tag_names == ["Hi\u1ebfn m\u00e1u"]
        assert {slug for _, slug in tags.rows} == {"sach-cu", "hien-mau"}

    def test_public_tag_feed_hides_drafts(self) -> None:
        service, _, _, _, org, owner = _service()
        draft = service.create_activity(
            org.id, owner, _fields(service, tag_names=["Bi\u1ec3n xanh"])
        )
        pub = service.create_activity(
            org.id,
            owner,
            _fields(
                service, slug="other-slug", tag_names=["Bi\u1ec3n xanh"]
            ),
        )
        service.set_status(org.id, pub.id, owner, "published")
        rows = service.list_public(tag_slug="bien-xanh")
        assert [r.id for r in rows] == [pub.id]
        # The raw name also resolves through the normalizer.
        rows2 = service.list_public(tag_slug="Bi\u1ec3n xanh!")
        assert [r.id for r in rows2] == [pub.id]

    def test_tag_feed_intersects_category(self) -> None:
        service, _, _, orgs, org, owner = _service()
        cat = CategoryService(
            categories=service._categories, orgs=orgs, access=service._access
        ).create_category(
            org.id, owner, "Eco", "eco", None, None, None, None
        )
        hit = service.create_activity(
            org.id,
            owner,
            _fields(service, tag_names=["R\u1eebng"], category_id=cat.id),
        )
        miss = service.create_activity(
            org.id,
            owner,
            _fields(service, slug="s2", tag_names=["R\u1eebng"]),
        )
        for row in (hit, miss):
            service.set_status(org.id, row.id, owner, "published")
        rows = service.list_public(
            tag_slug="rung", category_id=cat.id
        )
        assert [r.id for r in rows] == [hit.id]

    def test_non_public_status_filter_still_guards(self) -> None:
        service, _, _, _, _, _ = _service()
        with pytest.raises(InvalidOrgStateError):
            service.list_public(status="draft")
