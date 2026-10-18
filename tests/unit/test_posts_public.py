"""Unit tests for PublicPostService: guest post reads.

Only published `public`-visibility posts of a live org reach guests;
drafts, revisions, member-scoped posts and trash must never leave the
member board.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from core.exceptions import NotFoundError
from posts.public_service import PublicPostService
from tests.unit.member_fakes import FakeUsers
from tests.unit.org_fakes import FakeMedia, FakeOrgs
from tests.unit.workspace_fakes import (
    FakeCommentStore,
    FakePostStore,
    _uid,
)

NOW = datetime.now(UTC)


class Env:
    """Live org plus a service wired on the in-memory ports."""

    def __init__(self) -> None:
        self.orgs, self.posts = FakeOrgs(), FakePostStore()
        self.comments, self.users = FakeCommentStore(), FakeUsers()
        self.media = FakeMedia()
        self.owner = _uid()
        self.users.add(self.owner, "owner@example.com", "Owner")
        self.org = self.orgs.create(
            _uid(), self.owner, "Green Org", "green-org", "",
            "organization", "open", None, None, None, None,
            "verified", NOW,
        )
        self.service = PublicPostService(
            orgs=self.orgs,
            posts=self.posts,
            comments=self.comments,
            users=self.users,
            media=self.media,
        )

    def post(
        self,
        kind: str = "announcement",
        status: str = "active",
        **kwargs,
    ):
        return self.posts.create(
            _uid(), self.org.id, self.owner, kind,
            kwargs.pop("title", "T"), kwargs.pop("body", "B"),
            kwargs.pop("media_ids", []), NOW,
            status=status, **kwargs,
        )


def test_list_public_returns_announcement_briefs() -> None:
    env = Env()
    post = env.post(title="News", body="Announcement content.")
    env.comments.add(post.post_id, _uid(), env.owner, "hay", NOW)
    listing = env.service.list_public(env.org.id)
    assert listing.total == 1
    brief = listing.items[0]
    assert brief.id == post.post_id
    assert brief.title == "News"
    assert brief.excerpt == "Announcement content."
    assert brief.author_name == "Owner"
    assert brief.comment_count == 1
    assert brief.published_at is not None


def test_list_public_skips_non_public_kinds_and_states() -> None:
    env = Env()
    env.post(kind="discussion")
    env.post(kind="announcement", status="draft")
    env.post(kind="announcement", revision_of=_uid(), status="draft")
    trashed = env.post(kind="announcement")
    env.posts.soft_delete(trashed, NOW)
    listing = env.service.list_public(env.org.id)
    assert listing.total == 0 and listing.items == []


def test_list_public_scopes_to_one_org() -> None:
    env = Env()
    other = _uid()
    env.posts.create(
        _uid(), other, env.owner, "announcement", "T", "B", [], NOW
    )
    assert env.service.list_public(env.org.id).total == 0


def test_excerpt_truncates_long_bodies() -> None:
    env = Env()
    env.post(body="x  " * 300)
    brief = env.service.list_public(env.org.id).items[0]
    assert len(brief.excerpt) <= 203 and brief.excerpt.endswith("...")


def test_cover_url_prefers_cover_then_first_image() -> None:
    env = Env()
    cover = env.media.create_asset(
        _uid(), env.org.id, "posts/c.png", "image/png", 10, NOW, owner_type="organization")
    other = env.media.create_asset(
        _uid(), env.org.id, "posts/o.png", "image/png", 10, NOW, owner_type="organization")
    env.post(
        media_ids=[cover.asset_id, other.asset_id],
        cover_media_id=cover.asset_id,
    )
    brief = env.service.list_public(env.org.id).items[0]
    assert brief.cover_url == "/media/posts/c.png"


def test_list_public_page_paginates_and_guards_slug() -> None:
    env = Env()
    for index in range(5):
        env.post(title=f"Tin {index}")
    first = env.service.list_public_page("green-org", limit=2, page=1)
    last = env.service.list_public_page("green-org", limit=2, page=3)
    assert first.total == 5 and len(first.items) == 2
    assert last.total == 5 and len(last.items) == 1
    beyond = env.service.list_public_page("green-org", limit=2, page=9)
    assert beyond.items == []
    with pytest.raises(NotFoundError):
        env.service.list_public_page("no-such-org", limit=9, page=1)


def test_get_public_post_returns_snapshot() -> None:
    env = Env()
    post = env.post(title="Hello", body="Content")
    snap = env.service.get_public_post("green-org", post.post_id)
    assert snap.post_id == post.post_id
    assert snap.kind == "announcement"
    assert snap.author_name == "Owner"


def test_get_public_post_rejects_everything_not_public() -> None:
    env = Env()
    post = env.post()
    discussion = env.post(kind="discussion")
    members_ann = env.post(kind="announcement", visibility="members")
    draft = env.post(kind="announcement", status="draft")
    revision = env.post(
        kind="announcement", status="draft", revision_of=post.post_id
    )
    trashed = env.post(kind="announcement")
    env.posts.soft_delete(trashed, NOW)
    for slug, post_id in (
        ("green-org", _uid()),  # missing post
        ("green-org", discussion.post_id),  # member-scoped
        ("green-org", members_ann.post_id),  # members-only announcement
        ("green-org", draft.post_id),  # draft
        ("green-org", revision.post_id),  # revision draft
        ("green-org", trashed.post_id),  # in trash
        ("no-such-org", post.post_id),  # unknown slug
    ):
        with pytest.raises(NotFoundError):
            env.service.get_public_post(slug, post_id)


def test_audience_axis_decoupled_from_kind() -> None:
    env = Env()
    public_discussion = env.post(
        kind="discussion", visibility="public", title="Open thread"
    )
    env.post(kind="announcement", visibility="members", title="Internal")
    listing = env.service.list_public(env.org.id)
    assert listing.total == 1
    assert listing.items[0].id == public_discussion.post_id
    snap = env.service.get_public_post(
        "green-org", public_discussion.post_id
    )
    assert snap.kind == "discussion" and snap.visibility == "public"


def test_list_timeline_returns_org_attributed_teasers() -> None:
    env = Env()
    post = env.post(title="News", body="Announcement content.")
    page = env.service.list_timeline(None, 10)
    assert page.next_cursor is None
    assert [item.id for item in page.items] == [post.post_id]
    item = page.items[0]
    assert item.title == "News"
    assert item.excerpt == "Announcement content."
    assert item.author_name == "Owner"
    assert item.author_avatar_url is None
    assert item.org.id == env.org.id
    assert item.org.slug == "green-org"
    assert item.org.name == "Green Org"
    assert item.org.logo_url is None


def test_list_timeline_media_is_cover_first() -> None:
    """The teaser mosaic leads with the cover asset, then position order."""
    env = Env()
    first = env.media.create_asset(
        _uid(), env.org.id, "posts/a.png", "image/png", 10, NOW, owner_type="organization")
    cover = env.media.create_asset(
        _uid(), env.org.id, "posts/c.mp4", "video/mp4", 10, NOW, owner_type="organization")
    post = env.post(
        media_ids=[first.asset_id, cover.asset_id],
        cover_media_id=cover.asset_id,
    )
    item = env.service.list_timeline(None, 10).items[0]
    assert item.id == post.post_id
    assert item.media_count == 2
    assert [m.asset_id for m in item.media] == [
        cover.asset_id, first.asset_id,
    ]
    assert item.media[0].file_url == "/media/posts/c.mp4"


def test_list_timeline_carries_author_avatar_url() -> None:
    env = Env()
    asset = env.media.create_asset(
        _uid(), env.org.id, "users/u/a.png", "image/png", 10, NOW, owner_type="organization")
    env.users.add(
        env.owner,
        "owner@example.com",
        "Owner",
        avatar_media_id=asset.asset_id,
    )
    env.post(title="News")
    item = env.service.list_timeline(None, 10).items[0]
    assert item.author_avatar_url == "/media/users/u/a.png"


def test_list_timeline_ignores_dead_author_avatar_asset() -> None:
    env = Env()
    env.users.add(
        env.owner,
        "owner@example.com",
        "Owner",
        avatar_media_id=_uid(),
    )
    env.post(title="News")
    item = env.service.list_timeline(None, 10).items[0]
    assert item.author_avatar_url is None


def test_list_timeline_skips_non_public_and_dead_orgs() -> None:
    env = Env()
    env.post(kind="discussion")
    env.post(kind="announcement", status="draft")
    trashed = env.post()
    env.posts.soft_delete(trashed, NOW)
    dead_org = env.orgs.create(
        _uid(), env.owner, "Blue", "blue", "", "club", "invite",
        None, None, None, None, "pending", NOW,
    )
    env.posts.create(
        _uid(), dead_org.id, env.owner, "announcement", "X", "B", [], NOW
    )
    env.orgs.mark_deleted(dead_org.id, NOW)
    live = env.post(title="Live")
    page = env.service.list_timeline(None, 10)
    assert [item.id for item in page.items] == [live.post_id]
    assert page.next_cursor is None


def test_list_timeline_scans_past_drifted_feed_rows() -> None:
    env = Env()
    ghost = _uid()
    env.posts.timeline.insert(0, ghost)
    env.posts.timeline_orgs[ghost] = env.org.id
    live = env.post(title="Live")
    first = env.service.list_timeline(None, 1)
    assert [item.id for item in first.items] == [live.post_id]
    assert first.next_cursor is not None
    second = env.service.list_timeline(UUID(first.next_cursor), 10)
    assert second.items == []
    assert second.next_cursor is None


def test_list_timeline_paginates_by_cursor() -> None:
    env = Env()
    posts = [env.post(title=f"T{index}") for index in range(3)]
    first = env.service.list_timeline(None, 2)
    assert [item.id for item in first.items] == [
        posts[2].post_id, posts[1].post_id,
    ]
    assert first.next_cursor is not None
    second = env.service.list_timeline(UUID(first.next_cursor), 2)
    assert [item.id for item in second.items] == [posts[0].post_id]
    assert second.next_cursor is None


def test_public_post_media_lists_everything_cover_first() -> None:
    """Lightbox list: every attachment, cover first; hidden posts 404."""
    env = Env()
    ids = [
        env.media.create_asset(
            _uid(), env.org.id, f"posts/{i}.png", "image/png", 10, NOW, owner_type="organization").asset_id
        for i in range(8)
    ]
    cover = env.media.create_asset(
        _uid(), env.org.id, "posts/c.mp4", "video/mp4", 10, NOW, owner_type="organization")
    post = env.post(
        media_ids=[*ids, cover.asset_id], cover_media_id=cover.asset_id
    )
    items = env.service.list_public_post_media("green-org", post.post_id)
    assert len(items) == 9
    assert items[0].asset_id == cover.asset_id
    assert {item.asset_id for item in items[1:]} == set(ids)

    hidden = [
        env.post(kind="announcement", visibility="members").post_id,
        env.post(status="draft").post_id,
        env.posts.create(
            _uid(), _uid(), env.owner, "announcement", "T", "B", [], NOW
        ).post_id,  # foreign org: org_id mismatch must 404
    ]
    for post_id in hidden:
        with pytest.raises(NotFoundError):
            env.service.list_public_post_media("green-org", post_id)
    env.orgs.mark_deleted(env.org.id, NOW)
    with pytest.raises(NotFoundError):
        env.service.list_public_post_media("green-org", post.post_id)


def test_get_public_post_rejects_foreign_org_and_deleted_org() -> None:
    env = Env()
    post = env.post()
    other_org = env.orgs.create(
        _uid(), env.owner, "Blue", "blue", "", "club", "invite",
        None, None, None, None, "pending", NOW,
    )
    foreign = env.posts.create(
        _uid(), other_org.id, env.owner, "announcement", "T", "B", [], NOW
    )
    with pytest.raises(NotFoundError):  # post lives under another org
        env.service.get_public_post("green-org", foreign.post_id)
    env.orgs.mark_deleted(env.org.id, NOW)
    with pytest.raises(NotFoundError):  # deleted org hides everything
        env.service.get_public_post("green-org", post.post_id)
