"""Unit tests for PublicPostService: guest announcement reads.

Only published `announcement` posts of a live org are public; drafts,
revisions, discussions and trash must never leave the member board.
"""

from __future__ import annotations

from datetime import UTC, datetime

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
    post = env.post(title="Tin mừng", body="Nội dung thông báo.")
    env.comments.add(post.post_id, _uid(), env.owner, "hay", NOW)
    listing = env.service.list_public(env.org.id)
    assert listing.total == 1
    brief = listing.items[0]
    assert brief.id == post.post_id
    assert brief.title == "Tin mừng"
    assert brief.excerpt == "Nội dung thông báo."
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
        _uid(), env.org.id, "posts/c.png", "image/png", 10, NOW
    )
    other = env.media.create_asset(
        _uid(), env.org.id, "posts/o.png", "image/png", 10, NOW
    )
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
    post = env.post(title="Xin chào", body="Nội dung")
    snap = env.service.get_public_post("green-org", post.post_id)
    assert snap.post_id == post.post_id
    assert snap.kind == "announcement"
    assert snap.author_name == "Owner"


def test_get_public_post_rejects_everything_not_public() -> None:
    env = Env()
    post = env.post()
    discussion = env.post(kind="discussion")
    draft = env.post(kind="announcement", status="draft")
    revision = env.post(
        kind="announcement", status="draft", revision_of=post.post_id
    )
    trashed = env.post(kind="announcement")
    env.posts.soft_delete(trashed, NOW)
    for slug, post_id in (
        ("green-org", _uid()),  # missing post
        ("green-org", discussion.post_id),  # wrong kind
        ("green-org", draft.post_id),  # draft
        ("green-org", revision.post_id),  # revision draft
        ("green-org", trashed.post_id),  # in trash
        ("no-such-org", post.post_id),  # unknown slug
    ):
        with pytest.raises(NotFoundError):
            env.service.get_public_post(slug, post_id)


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
