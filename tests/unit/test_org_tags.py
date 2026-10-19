"""Unit tests: TagAdminService curation plus public directory search."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import uuid_utils

from activities.tag_admin_service import TagAdminService
from activities.tag_service import TagService
from core.exceptions import (
    ForbiddenError,
    InvalidTagMergeError,
    TagExistsError,
    TagNotFoundError,
)
from tests.unit.activity_fakes import (
    FakeAccess,
    FakeActivities,
    FakeActivityEvents,
    FakeOrgs,
    _fields,
    _org_with_owner,
)
from tests.unit.tag_fakes import FakeOrgTags

NOW = datetime.now(UTC)


def _setup(events: FakeActivityEvents | None = None):
    activities = FakeActivities()
    tags = FakeOrgTags(activities)
    orgs = FakeOrgs()
    access = FakeAccess()
    owner = uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner, "tag-admin")
    service = TagAdminService(
        tags=tags, orgs=orgs, access=access, events=events
    )
    return service, tags, activities, orgs, access, org, owner


def _member(orgs: FakeOrgs, org_id, with_manage: bool, access: FakeAccess):
    uid = uuid_utils.uuid7()
    orgs.members.setdefault(org_id, set()).add(uid)
    if with_manage:
        access.perms.setdefault((org_id, uid), set()).add("tag:manage")
    return uid


def _seed_activity(activities, org_id, owner, names, deleted: bool = False):
    row = activities.create(
        org_id, owner, _fields(None, tag_names=list(names)), NOW
    )
    if deleted:
        row.deleted_at = NOW
    return row


def _claim(tags, org_id, name):
    return tags.claim(org_id, uuid_utils.uuid7(), _slug(name), name, NOW)[0]


def _slug(name: str) -> str:
    from activities.model import tag_slug

    return tag_slug(name)


class TestSearchPublic:
    def test_dedupes_by_slug_across_orgs(self) -> None:
        _, tags, _, orgs, _, org, _ = _setup()
        other = _org_with_owner(orgs, uuid_utils.uuid7(), "tag-pub-b")
        third = _org_with_owner(orgs, uuid_utils.uuid7(), "tag-pub-c")
        _claim(tags, org.id, "Tr\u1ed3ng r\u1eebng")
        _claim(tags, other.id, "tr\u1ed3ng R\u1eeaNG")
        _claim(tags, third.id, "Tr\u1ed3ng r\u1eebng")
        svc = TagService(tags)
        rows = svc.search_public("trong")
        assert [(r.name, r.slug) for r in rows] == [
            ("Tr\u1ed3ng r\u1eebng", "trong-rung")
        ]

    def test_tie_breaks_alphabetical_and_matches_slug(self) -> None:
        _, tags, _, orgs, _, org, _ = _setup()
        other = _org_with_owner(orgs, uuid_utils.uuid7(), "tag-tie-b")
        # Same slug "tie-tag", one claim each: casefold order wins.
        _claim(tags, org.id, "tie-TAG")
        _claim(tags, other.id, "Tie Tag")
        _claim(tags, org.id, "Beach")
        svc = TagService(tags)
        rows = svc.search_public("tie-tag")
        assert [r.slug for r in rows] == ["tie-tag"]
        assert rows[0].name == "Tie Tag"
        assert [r.slug for r in svc.search_public("BEA")] == ["beach"]


class TestListTags:
    def test_counts_skip_trashed_and_flags_can_manage(self) -> None:
        service, tags, activities, orgs, access, org, owner = _setup()
        _claim(tags, org.id, "Alpha")
        _seed_activity(activities, org.id, owner, ["Alpha"])
        _seed_activity(activities, org.id, owner, ["Alpha"], deleted=True)
        page = service.list_tags(org.id, owner)
        assert page.can_manage is True
        assert [(i.slug, i.activity_count) for i in page.items] == [
            ("alpha", 1)
        ]

        member = _member(orgs, org.id, False, access)
        page = service.list_tags(org.id, member)
        assert page.can_manage is False

        manager = _member(orgs, org.id, True, access)
        assert service.list_tags(org.id, manager).can_manage is True

    def test_non_member_and_query_filter(self) -> None:
        service, tags, _, orgs, access, org, _ = _setup()
        _claim(tags, org.id, "Alpha")
        _claim(tags, org.id, "Beta")
        outsider = uuid_utils.uuid7()
        with pytest.raises(ForbiddenError):
            service.list_tags(org.id, outsider)
        page = service.list_tags(org.id, _member(orgs, org.id, False, access), "alp")
        assert [i.slug for i in page.items] == ["alpha"]


class TestCreateTag:
    def test_creates_and_conflict_on_duplicate_slug(self) -> None:
        service, tags, _, _, _, org, owner = _setup()
        snap = service.create_tag(org.id, owner, "Hi\u1ebfn m\u00e1u")
        assert snap.slug == "hien-mau"
        assert snap.activity_count == 0
        with pytest.raises(TagExistsError):
            service.create_tag(org.id, owner, "hien mau")

    def test_member_without_permission_is_denied_and_audited(self) -> None:
        service, _, _, orgs, access, org, _ = _setup()
        member = _member(orgs, org.id, False, access)
        with pytest.raises(ForbiddenError):
            service.create_tag(org.id, member, "Alpha")
        assert ("tag:manage", None, "denied") in access.audit


class TestRenameTag:
    def test_display_change_rewrites_activity_names(self) -> None:
        service, tags, activities, _, _, org, owner = _setup()
        _claim(tags, org.id, "Alpha")
        row = _seed_activity(activities, org.id, owner, ["Alpha"])
        snap = service.rename_tag(org.id, owner, "alpha", "ALPHA!")
        assert snap.slug == "alpha"
        assert snap.name == "ALPHA!"
        assert row.tag_names == ["ALPHA!"]

    def test_new_slug_moves_catalog_and_activities(self) -> None:
        service, tags, activities, _, _, org, owner = _setup()
        _claim(tags, org.id, "Alpha")
        row = _seed_activity(activities, org.id, owner, ["Alpha"])
        snap = service.rename_tag(org.id, owner, "alpha", "Gamma")
        assert snap.slug == "gamma"
        assert (org.id, "alpha") not in tags.rows
        assert row.tag_names == ["Gamma"]

    def test_taken_target_and_unknown_slug_fail(self) -> None:
        service, tags, _, _, _, org, owner = _setup()
        _claim(tags, org.id, "Alpha")
        _claim(tags, org.id, "Beta")
        with pytest.raises(TagExistsError):
            service.rename_tag(org.id, owner, "alpha", "Beta")
        with pytest.raises(TagNotFoundError):
            service.rename_tag(org.id, owner, "ghost", "X")

    def test_failed_retag_keeps_both_catalog_rows(self) -> None:
        class FailingTags(FakeOrgTags):
            def retag(self, org_id, slug, replacement, now):  # noqa: ANN001, ANN202
                raise RuntimeError("write timeout")

        activities = FakeActivities()
        tags = FailingTags(activities)
        orgs = FakeOrgs()
        owner = uuid_utils.uuid7()
        org = _org_with_owner(orgs, owner, "tag-crash")
        service = TagAdminService(
            tags=tags, orgs=orgs, access=FakeAccess()
        )
        _claim(tags, org.id, "Alpha")
        with pytest.raises(RuntimeError):
            service.rename_tag(org.id, owner, "alpha", "Gamma")
        assert (org.id, "alpha") in tags.rows
        assert (org.id, "gamma") in tags.rows

    def test_identical_name_is_a_noop(self) -> None:
        events = FakeActivityEvents()
        service, tags, _, _, access, org, owner = _setup(events)
        row = _claim(tags, org.id, "Alpha")
        snap = service.rename_tag(org.id, owner, "alpha", " Alpha ")
        assert snap.slug == "alpha"
        assert tags.rows[(org.id, "alpha")] is row
        assert events.tag_events == []
        assert not any(a[0] == "tag.rename" for a in access.audit)


class TestMergeTags:
    def test_merge_keeps_first_occurrence_and_drops_source(self) -> None:
        service, tags, activities, _, _, org, owner = _setup()
        _claim(tags, org.id, "Alpha")
        target = _claim(tags, org.id, "Beta")
        both = _seed_activity(activities, org.id, owner, ["Alpha", "Beta"])
        only = _seed_activity(activities, org.id, owner, ["Alpha", "Gamma"])
        snap = service.merge_tags(org.id, owner, "alpha", "beta")
        assert snap.slug == "beta"
        assert snap.activity_count == 2
        assert both.tag_names == ["Beta"]
        assert only.tag_names == ["Beta", "Gamma"]
        assert (org.id, "alpha") not in tags.rows
        assert snap.id == target.tag_id

    def test_self_merge_and_missing_target_fail(self) -> None:
        service, tags, _, _, _, org, owner = _setup()
        _claim(tags, org.id, "Alpha")
        with pytest.raises(InvalidTagMergeError):
            service.merge_tags(org.id, owner, "alpha", "alpha")
        with pytest.raises(TagNotFoundError):
            service.merge_tags(org.id, owner, "alpha", "ghost")
        with pytest.raises(TagNotFoundError):
            service.merge_tags(org.id, owner, "ghost", "alpha")


class TestEraseTag:
    def test_strips_tag_everywhere_including_trash(self) -> None:
        service, tags, activities, _, _, org, owner = _setup()
        _claim(tags, org.id, "Alpha")
        live = _seed_activity(activities, org.id, owner, ["Alpha", "Beta"])
        dead = _seed_activity(
            activities, org.id, owner, ["Alpha"], deleted=True
        )
        service.erase_tag(org.id, owner, "alpha")
        assert live.tag_names == ["Beta"]
        assert dead.tag_names == []
        assert (org.id, "alpha") not in tags.rows
        with pytest.raises(TagNotFoundError):
            service.erase_tag(org.id, owner, "alpha")


class TestTagEvents:
    def test_one_event_per_mutation_none_on_failures(self) -> None:
        events = FakeActivityEvents()
        service, tags, _, _, _, org, owner = _setup(events)
        service.create_tag(org.id, owner, "Alpha")
        service.rename_tag(org.id, owner, "alpha", "Beta")
        _claim(tags, org.id, "Gamma")
        service.merge_tags(org.id, owner, "beta", "gamma")
        service.erase_tag(org.id, owner, "gamma")
        assert events.tag_events == [
            (org.id, "created", "alpha", owner),
            (org.id, "renamed", "beta", owner),
            (org.id, "merged", "beta", owner),
            (org.id, "erased", "gamma", owner),
        ]
        with pytest.raises(TagNotFoundError):
            service.erase_tag(org.id, owner, "nope")
        service.create_tag(org.id, owner, "Ghost")
        with pytest.raises(TagExistsError):
            service.create_tag(org.id, owner, "ghost!")
        assert len(events.tag_events) == 5
        events2 = FakeActivityEvents()
        service2, _, _, orgs2, access2, org2, owner2 = _setup(events2)
        member = _member(orgs2, org2.id, False, access2)
        with pytest.raises(ForbiddenError):
            service2.create_tag(org2.id, member, "X")
        assert events2.tag_events == []
