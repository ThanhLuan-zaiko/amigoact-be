"""Unit tests: tag curation forwards post edges through the bridge."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import uuid_utils

from activities.tag_admin_service import TagAdminService
from tests.unit.activity_fakes import FakeAccess, FakeActivities, FakeOrgs, _org_with_owner
from tests.unit.tag_fakes import FakeOrgTags
from tests.unit.test_org_tags import _claim

NOW = datetime.now(UTC)


class RecordingPosts:
    """Records the post-index calls curation is supposed to make."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def usage(self, org_id: UUID) -> dict[str, int]:
        self.calls.append(("usage", org_id))
        return {}

    def trashed_usage(self, org_id: UUID) -> dict[str, int]:
        self.calls.append(("trashed", org_id))
        return {"alpha": 1}

    def retag(
        self, org_id: UUID, slug: str, replacement: str | None, now: datetime
    ) -> None:
        self.calls.append(("retag", slug, replacement))

    def snapshot_trash(self, org_id: UUID, slug: str) -> None:
        self.calls.append(("snapshot", slug))

    def restore(
        self, org_id: UUID, slug: str, name: str, now: datetime
    ) -> None:
        self.calls.append(("restore", slug, name))

    def forget_slug(self, org_id: UUID, slug: str) -> None:
        self.calls.append(("forget", slug))


def _service() -> tuple[TagAdminService, RecordingPosts, object, UUID]:
    activities = FakeActivities()
    tags = FakeOrgTags(activities)
    orgs = FakeOrgs()
    owner = uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner, "post-bridge")
    posts = RecordingPosts()
    service = TagAdminService(
        tags=tags, orgs=orgs, access=FakeAccess(), post_tags=posts
    )
    _claim(tags, org.id, "Alpha")
    return service, posts, org, owner


def test_rename_retags_posts_with_the_new_name() -> None:
    service, posts, org, owner = _service()
    service.rename_tag(org.id, owner, "alpha", "ALPHA!")
    assert ("retag", "alpha", "ALPHA!") in posts.calls


def test_trash_snapshots_then_detaches_posts() -> None:
    service, posts, org, owner = _service()
    service.trash_tag(org.id, owner, "alpha")
    kinds = [call[0] for call in posts.calls]
    assert kinds.index("snapshot") < kinds.index("retag")
    assert ("retag", "alpha", None) in posts.calls


def test_restore_reattaches_then_forgets_remembered_posts() -> None:
    service, posts, org, owner = _service()
    service.trash_tag(org.id, owner, "alpha")
    posts.calls.clear()
    service.restore_tag(org.id, owner, "alpha")
    kinds = [call[0] for call in posts.calls]
    assert ("restore", "alpha", "Alpha") in posts.calls
    assert kinds.index("restore") < kinds.index("forget")
