"""Unit tests for PostLifecycleService: drafts, publish, trash, purge."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from core.exceptions import (
    ForbiddenError,
    InvalidPostStateError,
    NotFoundError,
    PostContentRequiredError,
)
from posts.blocks import ImageBlock, ParagraphBlock
from posts.lifecycle_service import PostLifecycleService
from posts.service import PostService
from tests.unit.member_fakes import FakeAccess, FakeMembers, FakeOrgs, FakeUsers
from tests.unit.org_fakes import FakeMedia, FakeStore
from tests.unit.workspace_fakes import (
    NOW,
    FakeBoardEvents,
    FakeCommentStore,
    FakeNotify,
    FakePostStore,
    _uid,
    add_org,
)


class Env:
    """One org with owner, plain member and post:manage manager."""

    def __init__(self) -> None:
        self.posts, self.comments = FakePostStore(), FakeCommentStore()
        self.orgs, self.members, self.users = FakeOrgs(), FakeMembers(), FakeUsers()
        self.access, self.media, self.files = FakeAccess(), FakeMedia(), FakeStore()
        self.events, self.notify = FakeBoardEvents(), FakeNotify()
        self.owner = _uid()
        self.org_id = add_org(self.orgs, self.members, self.users, self.owner)
        args = (
            self.posts, self.comments, self.orgs, self.members, self.users,
            self.media, self.access, self.events, self.notify,
        )
        self.svc = PostService(*args)
        self.life = PostLifecycleService(*args, files=self.files)
        self.member = self.add_member("mem@x.com")
        self.manager = self.add_member("mgr@x.com")
        self.access.perms[(self.org_id, self.manager)] = {"post:manage"}

    def add_member(self, email: str) -> UUID:
        uid = _uid()
        self.users.add(uid, email, f"Name {email}")
        self.members.put(self.org_id, uid, "active", NOW)
        return uid

    def draft(self, author: UUID, title: str = "Draft", body: str = "b"):  # noqa: ANN201
        return self.svc.create_post(
            self.org_id, author, "discussion", title, body, [], status="draft"
        )

    def post(self, author: UUID, body: str = "live"):  # noqa: ANN201
        return self.svc.create_post(
            self.org_id, author, "discussion", "", body, []
        )


def test_draft_is_private_and_silent() -> None:
    env = Env()
    snap = env.draft(env.member)
    assert snap.status == "draft" and snap.published_at is None
    assert env.posts.feed.get(env.org_id, []) == []
    assert env.events.calls == []
    page = env.life.list_drafts(env.org_id, env.member)
    assert [p.post_id for p in page.items] == [snap.post_id]
    assert env.life.list_drafts(env.org_id, env.owner).items == []
    assert env.svc.get_post(env.org_id, snap.post_id, env.member).title == "Draft"
    with pytest.raises(NotFoundError):
        env.svc.get_post(env.org_id, snap.post_id, env.owner)


def test_publish_moves_draft_to_feed_and_notifies() -> None:
    env = Env()
    snap = env.svc.create_post(
        env.org_id, env.owner, "announcement", "News", "body", [],
        status="draft",
    )
    assert env.notify.calls == []
    published = env.life.publish(env.org_id, snap.post_id, env.owner)
    assert published.status == "published" and published.published_at
    assert env.posts.feed[env.org_id] == [snap.post_id]
    assert env.life.list_drafts(env.org_id, env.owner).items == []
    assert env.events.calls[-1][1] == "post.created"
    assert env.member in {call[0] for call in env.notify.calls}
    with pytest.raises(InvalidPostStateError):
        env.life.publish(env.org_id, snap.post_id, env.owner)


def test_publish_guards_content_and_author() -> None:
    env = Env()
    empty = env.draft(env.member, title="Only title", body="")
    with pytest.raises(PostContentRequiredError):
        env.life.publish(env.org_id, empty.post_id, env.member)
    with pytest.raises(NotFoundError):  # other people's drafts are invisible
        env.life.publish(env.org_id, empty.post_id, env.owner)


def test_unpublish_pulls_post_off_feed_and_pins() -> None:
    env = Env()
    snap = env.post(env.member)
    env.svc.set_pinned(env.org_id, snap.post_id, env.owner, True)
    back = env.life.unpublish(env.org_id, snap.post_id, env.member)
    assert back.status == "draft" and back.pinned_at is None
    assert env.posts.feed[env.org_id] == []
    assert env.posts.pinned[env.org_id] == []
    with pytest.raises(ForbiddenError):
        env.life.unpublish(env.org_id, env.post(env.member).post_id, env.owner)


def test_kind_changes_only_while_draft() -> None:
    env = Env()
    draft = env.draft(env.owner)
    edited = env.svc.update_post(
        env.org_id, draft.post_id, env.owner, "T", "", kind="announcement",
        blocks=[ParagraphBlock(type="paragraph", text="x")],
    )
    assert edited.kind == "announcement"
    live = env.post(env.owner)
    with pytest.raises(InvalidPostStateError):
        env.svc.update_post(
            env.org_id, live.post_id, env.owner, "T", "x",
            kind="announcement",
        )


def test_soft_delete_restore_round_trip() -> None:
    env = Env()
    snap = env.post(env.member)
    with pytest.raises(ForbiddenError):
        env.life.soft_delete(env.org_id, snap.post_id, env.add_member("o@x.com"))
    env.life.soft_delete(env.org_id, snap.post_id, env.manager)
    assert snap.post_id in env.posts.posts  # still stored, just trashed
    assert env.svc.list_posts(env.org_id, env.member).items == []
    with pytest.raises(NotFoundError):
        env.svc.get_post(env.org_id, snap.post_id, env.member)
    trash = env.life.list_trash(env.org_id, env.member)
    assert [p.deleted_at is not None for p in trash.items] == [True]
    restored = env.life.restore(env.org_id, snap.post_id, env.member)
    assert restored.deleted_at is None and restored.status == "published"
    assert env.posts.feed[env.org_id] == [snap.post_id]
    with pytest.raises(InvalidPostStateError):
        env.life.restore(env.org_id, snap.post_id, env.member)


def test_trash_visibility_by_role() -> None:
    env = Env()
    mine = env.post(env.member)
    other = env.post(env.owner)
    private = env.draft(env.member)
    for post_id, actor in (
        (mine.post_id, env.member),
        (other.post_id, env.owner),
        (private.post_id, env.member),
    ):
        env.life.soft_delete(env.org_id, post_id, actor)
    as_member = {p.post_id for p in env.life.list_trash(env.org_id, env.member).items}
    as_manager = {p.post_id for p in env.life.list_trash(env.org_id, env.manager).items}
    assert as_member == {mine.post_id, private.post_id}
    assert as_manager == {mine.post_id, other.post_id}  # drafts stay private
    with pytest.raises(NotFoundError):
        env.life.hard_delete(env.org_id, private.post_id, env.manager)
    restored = env.life.restore(env.org_id, private.post_id, env.member)
    assert restored.status == "draft"
    assert env.life.list_drafts(env.org_id, env.member).items[0].post_id == (
        private.post_id
    )


def test_revision_stages_edits_until_publish() -> None:
    env = Env()
    snap = env.post(env.member, body="v1")
    events = len(env.events.calls)
    rev = env.life.get_or_create_revision(env.org_id, snap.post_id, env.member)
    assert rev.post_id != snap.post_id
    assert rev.status == "draft" and rev.revision_of == snap.post_id
    assert rev.body == "v1"
    again = env.life.get_or_create_revision(env.org_id, snap.post_id, env.member)
    assert again.post_id == rev.post_id  # idempotent
    assert len(env.events.calls) == events  # revisions stay silent
    assert env.svc.get_post(env.org_id, snap.post_id, env.member).body == "v1"
    drafts = env.life.list_drafts(env.org_id, env.member)
    assert [p.post_id for p in drafts.items] == [rev.post_id]


def test_revision_requires_published_post_and_author() -> None:
    env = Env()
    snap = env.post(env.member)
    with pytest.raises(ForbiddenError):
        env.life.get_or_create_revision(env.org_id, snap.post_id, env.owner)
    draft = env.draft(env.member)
    with pytest.raises(InvalidPostStateError):
        env.life.get_or_create_revision(env.org_id, draft.post_id, env.member)


def test_publish_revision_folds_into_live_post() -> None:
    env = Env()
    snap = env.post(env.member, body="v1")
    rev = env.life.get_or_create_revision(env.org_id, snap.post_id, env.member)
    edited = env.svc.update_post(
        env.org_id, rev.post_id, env.member, "New title", "v2",
    )
    assert edited.title == "New title"
    merged = env.life.publish(env.org_id, rev.post_id, env.member)
    assert merged.post_id == snap.post_id
    assert merged.status == "published" and merged.edited_at is not None
    assert merged.title == "New title" and merged.body == "v2"
    assert rev.post_id not in env.posts.posts
    assert env.posts.feed[env.org_id] == [snap.post_id]
    assert env.life.list_drafts(env.org_id, env.member).items == []
    assert env.events.calls[-1][1] == "post.updated"
    assert env.events.calls[-1][2] == snap.post_id


def test_revision_kind_is_locked_to_parent() -> None:
    env = Env()
    snap = env.post(env.member)
    rev = env.life.get_or_create_revision(env.org_id, snap.post_id, env.member)
    with pytest.raises(InvalidPostStateError):
        env.svc.update_post(
            env.org_id, rev.post_id, env.member, "T", "x",
            kind="announcement",
        )


def test_unpublish_folds_open_revision_into_draft() -> None:
    env = Env()
    snap = env.post(env.member, body="v1")
    rev = env.life.get_or_create_revision(env.org_id, snap.post_id, env.member)
    env.svc.update_post(env.org_id, rev.post_id, env.member, "v2", "v2 body")
    back = env.life.unpublish(env.org_id, snap.post_id, env.member)
    assert back.status == "draft" and back.body == "v2 body"
    assert rev.post_id not in env.posts.posts
    drafts = env.life.list_drafts(env.org_id, env.member)
    assert [p.post_id for p in drafts.items] == [snap.post_id]


def test_trash_and_purge_cascade_to_revisions() -> None:
    env = Env()
    snap = env.post(env.member)
    rev = env.life.get_or_create_revision(env.org_id, snap.post_id, env.member)
    env.life.soft_delete(env.org_id, snap.post_id, env.member)
    trashed = {
        p.post_id for p in env.life.list_trash(env.org_id, env.member).items
    }
    assert trashed == {snap.post_id, rev.post_id}
    env.life.restore(env.org_id, snap.post_id, env.member)
    assert env.svc.get_post(env.org_id, snap.post_id, env.member).status == (
        "published"
    )
    env.life.restore(env.org_id, rev.post_id, env.member)
    env.life.hard_delete(env.org_id, snap.post_id, env.member)
    assert snap.post_id not in env.posts.posts
    assert rev.post_id not in env.posts.posts


def test_purging_revision_keeps_live_assets() -> None:
    env = Env()
    att = env.media.create_asset(
        _uid(), env.org_id, "orgs/x/keep.png", "image/png", 1, NOW,
        role="attachment",
    )
    env.files.files["orgs/x/keep.png"] = b"1"
    snap = env.svc.create_post(
        env.org_id, env.member, "discussion", "T", "", [],
        blocks=[ImageBlock(type="image", asset_id=att.asset_id)],
    )
    rev = env.life.get_or_create_revision(env.org_id, snap.post_id, env.member)
    env.life.hard_delete(env.org_id, rev.post_id, env.member)
    assert rev.post_id not in env.posts.posts
    assert att.asset_id in env.media.assets  # still used by the live post


def test_hard_delete_purges_attachments_only() -> None:
    env = Env()
    att = env.media.create_asset(
        _uid(), env.org_id, "orgs/x/att.png", "image/png", 1, NOW,
        role="attachment",
    )
    gal = env.media.create_asset(
        _uid(), env.org_id, "orgs/x/gal.png", "image/png", 1, NOW,
    )
    env.files.files["orgs/x/att.png"] = b"1"
    env.files.files["orgs/x/gal.png"] = b"2"
    snap = env.svc.create_post(
        env.org_id, env.member, "discussion", "T", "", [],
        blocks=[
            ImageBlock(type="image", asset_id=att.asset_id),
            ImageBlock(type="image", asset_id=gal.asset_id),
        ],
    )
    env.comments.add(snap.post_id, _uid(), env.owner, "hi", NOW)
    with pytest.raises(ForbiddenError):
        env.life.hard_delete(env.org_id, snap.post_id, env.add_member("z@x.com"))
    env.life.hard_delete(env.org_id, snap.post_id, env.member)
    assert snap.post_id not in env.posts.posts
    assert env.comments.count(snap.post_id) == 0
    assert att.asset_id not in env.media.assets
    assert gal.asset_id in env.media.assets
    assert "orgs/x/att.png" not in env.files.files
    assert "orgs/x/gal.png" in env.files.files
    assert env.events.calls[-1][1] == "post.deleted"


def test_snapshot_timestamps_carry_utc_offset() -> None:
    """Scylla rows are naive UTC; snapshots must reattach the offset."""
    env = Env()
    snap = env.post(env.member)
    row = env.posts.posts[snap.post_id]
    naive = datetime(2026, 10, 13, 2, 30)
    row.created_at, row.published_at, row.updated_at = naive, naive, naive
    loaded = env.svc.get_post(env.org_id, snap.post_id, env.member)
    aware = datetime(2026, 10, 13, 2, 30, tzinfo=UTC)
    assert loaded.created_at == aware
    assert loaded.published_at == aware
    assert loaded.updated_at == aware
    assert loaded.deleted_at is None
