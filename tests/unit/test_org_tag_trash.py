"""Unit tests: tag soft delete, restore, erase and slug reservation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import uuid_utils

from activities.tag_service import TagService
from core.exceptions import (
    ForbiddenError,
    InvalidOrgStateError,
    TagDeletedError,
    TagNotFoundError,
)
from tests.unit.activity_fakes import (
    FakeAccess,
    FakeActivities,
    FakeActivityEvents,
    FakeOrgs,
)
from tests.unit.test_org_tags import (
    _claim,
    _member,
    _seed_activity,
    _setup,
)

NOW = datetime.now(UTC)


class TestTrashTag:
    def test_detaches_and_remembers(self) -> None:
        service, tags, activities, orgs, access, org, owner = _setup()
        _claim(tags, org.id, "Alpha")
        live = _seed_activity(activities, org.id, owner, ["Alpha", "Beta"])
        dead = _seed_activity(
            activities, org.id, owner, ["Alpha"], deleted=True
        )

        snap = service.trash_tag(org.id, owner, "alpha")

        assert live.tag_names == ["Beta"]
        assert dead.tag_names == []
        assert snap.deleted_at is not None
        assert tags.rows[(org.id, "alpha")].deleted_at is not None
        # Trashed rows leave the public directory and the live list.
        assert all(
            r.slug != "alpha" for r in TagService(tags).search_public("")
        )
        page = service.list_tags(org.id, owner)
        assert [i.slug for i in page.items] == []
        assert page.trash_count == 1
        trash = service.list_tags(org.id, owner, trash=True)
        assert [i.slug for i in trash.items] == ["alpha"]
        # The activity-trashed one is excluded from the count.
        assert trash.items[0].activity_count == 1

    def test_already_trashed_and_member_denied(self) -> None:
        service, tags, _, orgs, access, org, owner = _setup()
        _claim(tags, org.id, "Alpha")
        service.trash_tag(org.id, owner, "alpha")
        with pytest.raises(TagDeletedError):
            service.trash_tag(org.id, owner, "alpha")
        member = _member(orgs, org.id, False, access)
        with pytest.raises(ForbiddenError):
            service.trash_tag(org.id, member, "alpha")


class TestRestoreTag:
    def test_reattaches_at_the_end(self) -> None:
        service, tags, activities, _, _, org, owner = _setup()
        _claim(tags, org.id, "Alpha")
        act = _seed_activity(activities, org.id, owner, ["Alpha", "Beta"])
        service.trash_tag(org.id, owner, "alpha")
        snap = service.restore_tag(org.id, owner, "alpha")
        assert snap.deleted_at is None
        assert act.tag_names == ["Beta", "Alpha"]
        assert tags.rows[(org.id, "alpha")].deleted_at is None

    def test_skips_full_and_purged_activities(self) -> None:
        service, tags, activities, _, _, org, owner = _setup()
        _claim(tags, org.id, "Alpha")
        full = _seed_activity(
            activities, org.id, owner,
            ["Alpha"] + [f"T{i}" for i in range(10)],
        )
        gone = _seed_activity(activities, org.id, owner, ["Alpha"])
        service.trash_tag(org.id, owner, "alpha")
        activities.delete_everything(gone.id)
        service.restore_tag(org.id, owner, "alpha")
        # `full` hit the 10-tag cap; `gone` was purged, so only its
        # remembered row is dropped by the purge maintenance.
        assert "Alpha" not in (full.tag_names or [])
        assert len(full.tag_names or []) == 10
        trash = service.list_tags(org.id, owner, trash=True)
        assert trash.items == []

    def test_live_and_unknown_guards(self) -> None:
        service, tags, _, _, _, org, owner = _setup()
        _claim(tags, org.id, "Alpha")
        with pytest.raises(InvalidOrgStateError):
            service.restore_tag(org.id, owner, "alpha")
        with pytest.raises(TagNotFoundError):
            service.restore_tag(org.id, owner, "ghost")


class TestEraseTag:
    def test_trashed_tag_purges_memory_and_blocks_restore(self) -> None:
        service, tags, activities, _, _, org, owner = _setup()
        _claim(tags, org.id, "Alpha")
        act = _seed_activity(activities, org.id, owner, ["Alpha"])
        service.trash_tag(org.id, owner, "alpha")
        service.erase_tag(org.id, owner, "alpha")
        assert (org.id, "alpha") not in tags.rows
        assert tags.trash_edges.get((org.id, "alpha")) in (None, set())
        assert act.tag_names == []
        with pytest.raises(TagNotFoundError):
            service.restore_tag(org.id, owner, "alpha")


class TestTrashedSlugIsReserved:
    def test_ensure_create_rename_merge_all_blocked(self) -> None:
        service, tags, _, _, _, org, owner = _setup()
        _claim(tags, org.id, "Alpha")
        _claim(tags, org.id, "Beta")
        service.trash_tag(org.id, owner, "alpha")

        svc = TagService(tags)
        with pytest.raises(TagDeletedError):
            svc.ensure(org.id, ["alpha"])
        with pytest.raises(TagDeletedError):
            service.create_tag(org.id, owner, "Alpha")
        with pytest.raises(TagDeletedError):
            service.rename_tag(org.id, owner, "beta", "Alpha")
        with pytest.raises(TagDeletedError):
            service.rename_tag(org.id, owner, "alpha", "Gamma")
        with pytest.raises(TagDeletedError):
            service.merge_tags(org.id, owner, "alpha", "beta")
        with pytest.raises(TagDeletedError):
            service.merge_tags(org.id, owner, "beta", "alpha")


class TestTrashListing:
    def test_member_denied_and_trash_count_visibility(self) -> None:
        service, tags, _, orgs, access, org, owner = _setup()
        _claim(tags, org.id, "Alpha")
        service.trash_tag(org.id, owner, "alpha")

        member = _member(orgs, org.id, False, access)
        with pytest.raises(ForbiddenError):
            service.list_tags(org.id, member, trash=True)

        live_member = service.list_tags(org.id, member)
        assert live_member.trash_count == 0
        live_owner = service.list_tags(org.id, owner)
        assert live_owner.trash_count == 1


class TestTrashEvents:
    def test_one_event_each_and_none_on_failures(self) -> None:
        events = FakeActivityEvents()
        service, tags, _, _, _, org, owner = _setup(events)
        service.create_tag(org.id, owner, "Alpha")
        service.trash_tag(org.id, owner, "alpha")
        service.restore_tag(org.id, owner, "alpha")
        service.erase_tag(org.id, owner, "alpha")
        assert events.tag_events == [
            (org.id, "created", "alpha", owner),
            (org.id, "trashed", "alpha", owner),
            (org.id, "restored", "alpha", owner),
            (org.id, "erased", "alpha", owner),
        ]
        with pytest.raises(TagNotFoundError):
            service.trash_tag(org.id, owner, "nope")
        with pytest.raises(TagNotFoundError):
            service.restore_tag(org.id, owner, "nope")
        with pytest.raises(TagNotFoundError):
            service.erase_tag(org.id, owner, "nope")
        assert len(events.tag_events) == 4
