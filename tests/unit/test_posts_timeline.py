"""Unit tests for the announcements:feed fan-out on board lifecycle moves.

Every action that changes a published public post's guest reachability
must emit a refetch hint to the public timeline; member-scoped posts,
drafts and trash-only moves stay silent.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from core.exceptions import ForbiddenError, InvalidPostStateError
from posts.lifecycle_service import PostLifecycleService
from posts.service import PostService
from tests.unit.member_fakes import (
    FakeAccess,
    FakeMembers,
    FakeOrgs,
    FakeUsers,
)
from tests.unit.org_fakes import FakeMedia, FakeStore
from tests.unit.workspace_fakes import (
    NOW,
    FakeBoardEvents,
    FakeCommentStore,
    FakeNotify,
    FakePostStore,
    FakeTimelineEvents,
    _uid,
    add_org,
)


class Env:
    """One org with owner + member, board services wired like prod."""

    def __init__(self) -> None:
        self.posts, self.comments = FakePostStore(), FakeCommentStore()
        self.orgs = FakeOrgs()
        self.members, self.users = FakeMembers(), FakeUsers()
        self.access = FakeAccess()
        self.media, self.files = FakeMedia(), FakeStore()
        self.events, self.notify = FakeBoardEvents(), FakeNotify()
        self.timeline = FakeTimelineEvents()
        self.owner = _uid()
        self.org_id = add_org(self.orgs, self.members, self.users, self.owner)
        args = (
            self.posts, self.comments, self.orgs, self.members, self.users,
            self.media, self.access, self.events, self.notify,
        )
        self.svc = PostService(*args, announcements=self.timeline)
        self.life = PostLifecycleService(
            *args, files=self.files, announcements=self.timeline
        )
        self.member = _uid()
        self.users.add(self.member, "mem@x.com", "Member")
        self.members.put(self.org_id, self.member, "active", NOW)

    def announcement(self, title: str = "News"):  # noqa: ANN202
        return self.svc.create_post(
            self.org_id, self.owner, "announcement", title, "body", []
        )

    def actions(self) -> list[str]:
        return [call[0] for call in self.timeline.calls]


def test_announcement_lifecycle_fans_out_to_public_timeline() -> None:
    env = Env()
    snap = env.announcement()
    assert env.timeline.calls == [("created", snap.post_id, env.org_id)]
    env.svc.update_post(
        env.org_id, snap.post_id, env.owner, "News 2", "edited"
    )
    env.life.unpublish(env.org_id, snap.post_id, env.owner)
    env.life.publish(env.org_id, snap.post_id, env.owner)
    env.life.soft_delete(env.org_id, snap.post_id, env.owner)
    env.life.restore(env.org_id, snap.post_id, env.owner)
    env.life.hard_delete(env.org_id, snap.post_id, env.owner)
    assert env.actions() == [
        "created", "updated", "removed", "created", "removed",
        "created", "removed",
    ]


def test_discussion_lifecycle_stays_off_the_public_timeline() -> None:
    env = Env()
    snap = env.svc.create_post(
        env.org_id, env.member, "discussion", "", "live", []
    )
    env.svc.update_post(env.org_id, snap.post_id, env.member, "", "edited")
    env.life.unpublish(env.org_id, snap.post_id, env.member)
    env.life.publish(env.org_id, snap.post_id, env.member)
    env.life.soft_delete(env.org_id, snap.post_id, env.owner)
    env.life.hard_delete(env.org_id, snap.post_id, env.owner)
    assert env.timeline.calls == []


def test_draft_announcement_is_silent_until_publish() -> None:
    env = Env()
    snap = env.svc.create_post(
        env.org_id, env.owner, "announcement", "News", "body", [],
        status="draft",
    )
    assert env.timeline.calls == []
    env.life.publish(env.org_id, snap.post_id, env.owner)
    assert env.timeline.calls == [("created", snap.post_id, env.org_id)]


def test_revision_publish_refreshes_public_timeline() -> None:
    env = Env()
    snap = env.announcement()
    rev = env.life.get_or_create_revision(
        env.org_id, snap.post_id, env.owner
    )
    env.svc.update_post(
        env.org_id, rev.post_id, env.owner, "News v2", "edited"
    )
    env.life.publish(env.org_id, rev.post_id, env.owner)
    assert env.actions() == ["created", "updated"]


def test_public_hint_carries_org_id_for_refetch() -> None:
    env = Env()
    snap = env.announcement()
    action, post_id, org_id = env.timeline.calls[0]
    assert action == "created"
    assert post_id == snap.post_id
    assert isinstance(org_id, UUID) and org_id == env.org_id


def test_public_discussion_reaches_the_timeline() -> None:
    env = Env()
    snap = env.svc.create_post(
        env.org_id, env.owner, "discussion", "", "open thread", [],
        visibility="public",
    )
    assert snap.visibility == "public"
    assert env.timeline.calls == [("created", snap.post_id, env.org_id)]


def test_members_announcement_stays_off_the_timeline() -> None:
    env = Env()
    snap = env.svc.create_post(
        env.org_id, env.owner, "announcement", "Internal", "memo", [],
        visibility="members",
    )
    assert snap.visibility == "members"
    assert env.timeline.calls == []
    assert env.posts.timeline == []
    # Member-facing fan-out still happens: board emit + notifications.
    assert env.events.calls[-1][1] == "post.created"
    assert env.notify.calls != []


def test_visibility_flip_moves_the_post_on_and_off_timeline() -> None:
    env = Env()
    snap = env.svc.create_post(
        env.org_id, env.owner, "discussion", "", "live", [],
        visibility="members",
    )
    assert env.timeline.calls == []
    env.svc.update_post(
        env.org_id, snap.post_id, env.owner, "", "live",
        visibility="public",
    )
    env.svc.update_post(
        env.org_id, snap.post_id, env.owner, "", "live",
        visibility="members",
    )
    assert env.actions() == ["created", "removed"]
    assert env.posts.timeline == []


def test_member_without_announce_permission_stays_member_scoped() -> None:
    env = Env()
    with pytest.raises(ForbiddenError):
        env.svc.create_post(
            env.org_id, env.member, "discussion", "", "x", [],
            visibility="public",
        )
    snap = env.svc.create_post(
        env.org_id, env.member, "discussion", "", "own post", [],
    )
    with pytest.raises(ForbiddenError):
        env.svc.update_post(
            env.org_id, snap.post_id, env.member, "", "own post",
            visibility="public",
        )
    # ...but taking an own public post private is always allowed.
    env.access.perms[(env.org_id, env.member)] = {"post:announce"}
    public = env.svc.create_post(
        env.org_id, env.member, "discussion", "", "open", [],
        visibility="public",
    )
    del env.access.perms[(env.org_id, env.member)]
    snap2 = env.svc.update_post(
        env.org_id, public.post_id, env.member, "", "open",
        visibility="members",
    )
    assert snap2.visibility == "members"


def test_revision_inherits_audience_and_cannot_change_it() -> None:
    env = Env()
    snap = env.announcement()
    rev = env.life.get_or_create_revision(
        env.org_id, snap.post_id, env.owner
    )
    assert rev.visibility == "public"
    with pytest.raises(InvalidPostStateError):
        env.svc.update_post(
            env.org_id, rev.post_id, env.owner, "News", "edited",
            visibility="members",
        )


def test_visibility_flip_on_draft_stays_silent_until_publish() -> None:
    env = Env()
    snap = env.svc.create_post(
        env.org_id, env.owner, "discussion", "", "body", [],
        status="draft",
    )
    env.svc.update_post(
        env.org_id, snap.post_id, env.owner, "", "body",
        visibility="public",
    )
    assert env.timeline.calls == []
    env.life.publish(env.org_id, snap.post_id, env.owner)
    assert env.timeline.calls == [("created", snap.post_id, env.org_id)]
