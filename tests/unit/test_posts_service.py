"""Unit tests for PostService: board CRUD, pins, kinds, attachments."""

from __future__ import annotations

from uuid import UUID

import pytest

from core.exceptions import (
    ForbiddenError,
    NotFoundError,
    PostContentRequiredError,
)
from posts.blocks import ParagraphBlock, VideoBlock
from posts.service import PostService
from tests.unit.member_fakes import (
    FakeAccess,
    FakeMembers,
    FakeOrgs,
    FakeUsers,
)
from tests.unit.org_fakes import FakeMedia
from tests.unit.workspace_fakes import (
    NOW,
    FakeBoardEvents,
    FakeCommentStore,
    FakeNotify,
    FakePostStore,
    _uid,
    add_org,
)


def _service():
    posts, comments = FakePostStore(), FakeCommentStore()
    orgs, members, users = FakeOrgs(), FakeMembers(), FakeUsers()
    access, media = FakeAccess(), FakeMedia()
    events, notify = FakeBoardEvents(), FakeNotify()
    owner = _uid()
    org_id = add_org(orgs, members, users, owner, name="Alpha")
    service = PostService(
        posts, comments, orgs, members, users, media, access, events,
        notify,
    )
    return (
        service, posts, orgs, members, users, access, media, events,
        notify, org_id, owner,
    )


def _member(
    members: FakeMembers, users: FakeUsers, org_id: UUID,
    email: str = "mem@x.com",
) -> UUID:
    uid = _uid()
    users.add(uid, email, f"Name {email}")
    members.put(org_id, uid, "active", NOW)
    return uid


def test_member_creates_discussion() -> None:
    (svc, posts, _, _, _, access, _, events, _, org_id,
     owner) = _service()
    snap = svc.create_post(
        org_id, owner, "discussion", "", "hello board", []
    )
    assert snap.kind == "discussion"
    assert snap.author_name == "Owner"
    assert posts.feed[org_id] == [snap.post_id]
    assert events.calls[-1][1] == "post.created"
    assert ("post.create", snap.post_id, "allowed") in access.audit


def test_non_member_cannot_post_or_read() -> None:
    svc, _, _, _, _, access, _, _, _, org_id, _ = _service()
    outsider = _uid()
    with pytest.raises(ForbiddenError):
        svc.create_post(org_id, outsider, "discussion", "", "x", [])
    with pytest.raises(ForbiddenError):
        svc.list_posts(org_id, outsider)
    assert ("post.create", None, "denied") in access.audit


def test_announcement_requires_permission() -> None:
    (svc, _, _, members, users, access, _, _, _, org_id,
     owner) = _service()
    member = _member(members, users, org_id)
    with pytest.raises(ForbiddenError):
        svc.create_post(org_id, member, "announcement", "T", "b", [])
    access.perms[(org_id, member)] = {"post:announce"}
    snap = svc.create_post(
        org_id, member, "announcement", "T", "b", []
    )
    assert snap.kind == "announcement"
    owner_post = svc.create_post(
        org_id, owner, "announcement", "T2", "b", []
    )
    assert owner_post.kind == "announcement"


def test_announcement_notifies_active_members_except_author() -> None:
    (svc, _, _, members, users, _, _, _, notify, org_id,
     owner) = _service()
    member = _member(members, users, org_id)
    suspended = _uid()
    users.add(suspended, "s@x.com", "Susp")
    members.put(org_id, suspended, "suspended", NOW)
    svc.create_post(org_id, owner, "announcement", "Hi", "b", [])
    notified = {call[0] for call in notify.calls}
    assert member in notified
    assert owner not in notified  # the author never notifies themselves
    assert suspended not in notified
    assert all(call[1] == "announcement" for call in notify.calls)


def test_feed_newest_first_with_numbered_pages() -> None:
    svc, _, _, _, _, _, _, _, _, org_id, owner = _service()
    ids = [
        svc.create_post(org_id, owner, "discussion", "", f"p{i}", []).post_id
        for i in range(4)
    ]
    first = svc.list_posts(org_id, owner, limit=2, page=1)
    assert [item.post_id for item in first.items] == [ids[3], ids[2]]
    assert first.total == 4
    second = svc.list_posts(org_id, owner, limit=2, page=2)
    assert [item.post_id for item in second.items] == [ids[1], ids[0]]
    assert second.total == 4
    assert first.viewer_role == "owner"
    assert second.pinned == []  # the rail only ships on the first page
    assert svc.list_posts(org_id, owner, limit=2, page=3).items == []


def test_kind_filter_pages_without_skipping() -> None:
    (svc, _, _, members, users, access, _, _, _, org_id,
     owner) = _service()
    member = _member(members, users, org_id)
    access.perms[(org_id, member)] = {"post:announce"}
    ann1 = svc.create_post(org_id, member, "announcement", "A", "b", [])
    svc.create_post(org_id, owner, "discussion", "", "d1", [])
    ann2 = svc.create_post(org_id, member, "announcement", "B", "b", [])
    page = svc.list_posts(org_id, owner, limit=5, kind="announcement")
    assert [p.post_id for p in page.items] == [
        ann2.post_id, ann1.post_id
    ]
    assert page.total == 2
    assert all(p.kind == "announcement" for p in page.items)


def test_pinned_rail_and_permissions() -> None:
    (svc, _, _, members, users, access, _, _, _, org_id,
     owner) = _service()
    member = _member(members, users, org_id)
    snap = svc.create_post(org_id, member, "discussion", "", "pin me", [])
    with pytest.raises(ForbiddenError):
        svc.set_pinned(org_id, snap.post_id, member, True)
    pinned = svc.set_pinned(org_id, snap.post_id, owner, True)
    assert pinned.pinned_at is not None
    page = svc.list_posts(org_id, member)
    assert [p.post_id for p in page.pinned] == [snap.post_id]
    svc.set_pinned(org_id, snap.post_id, owner, False)
    assert svc.list_posts(org_id, member).pinned == []


def test_update_only_by_author() -> None:
    (svc, _, _, members, users, _, _, _, _, org_id, owner) = _service()
    member = _member(members, users, org_id)
    snap = svc.create_post(org_id, owner, "discussion", "", "v1", [])
    with pytest.raises(ForbiddenError):
        svc.update_post(org_id, snap.post_id, member, "t", "v2")
    edited = svc.update_post(org_id, snap.post_id, owner, "t", "v2")
    assert edited.body == "v2" and edited.edited_at is not None


def test_update_with_blocks_replaces_article_and_media() -> None:
    (svc, posts, _, _, _, _, media, _, _, org_id, owner) = _service()
    img = media.create_asset(_uid(), org_id, "orgs/a.png", "image/png", 1, NOW)
    vid = media.create_asset(_uid(), org_id, "orgs/v.mp4", "video/mp4", 1, NOW)
    snap = svc.create_post(org_id, owner, "discussion", "T", "old", [])
    blocks = [
        ParagraphBlock(type="paragraph", text="Intro"),
        VideoBlock(type="video", asset_id=vid.asset_id, caption="Clip"),
        ParagraphBlock(type="paragraph", text="  "),
    ]
    edited = svc.update_post(
        org_id, snap.post_id, owner, "T", "", blocks=blocks,
        cover_media_id=img.asset_id, touch_cover=True,
    )
    assert [b["type"] for b in edited.blocks] == ["paragraph", "video"]
    assert edited.body == "Intro\n\nClip"
    assert edited.cover_media_id == img.asset_id
    assert [m.asset_id for m in edited.media] == [img.asset_id, vid.asset_id]
    assert edited.media[0].file_url == "/media/orgs/a.png"
    assert [link.asset_id for link in posts.media[snap.post_id]] == [
        img.asset_id, vid.asset_id
    ]


def test_block_media_kind_must_match_asset() -> None:
    (svc, _, _, _, _, _, media, _, _, org_id, owner) = _service()
    img = media.create_asset(_uid(), org_id, "orgs/a.png", "image/png", 1, NOW)
    with pytest.raises(NotFoundError):
        svc.create_post(
            org_id, owner, "discussion", "T", "", [],
            blocks=[VideoBlock(type="video", asset_id=img.asset_id)],
        )
    with pytest.raises(PostContentRequiredError):
        svc.create_post(
            org_id, owner, "discussion", "T", "", [],
            blocks=[ParagraphBlock(type="paragraph", text="")],
        )


def test_post_lookup_scoped_to_org() -> None:
    (svc, _, orgs, members, users, _, _, _, _, org_id,
     owner) = _service()
    other = _uid()
    other_org = add_org(orgs, members, users, other)
    snap = svc.create_post(org_id, owner, "discussion", "", "x", [])
    members.put(other_org, owner, "active", NOW)
    with pytest.raises(NotFoundError):
        svc.get_post(other_org, snap.post_id, owner)


def test_media_attachment_validation() -> None:
    (svc, _, orgs, members, users, _, media, _, _, org_id,
     owner) = _service()
    good = media.create_asset(
        _uid(), org_id, "/m/a.png", "image/png", 10, NOW
    )
    foreign_org = add_org(orgs, members, users, _uid())
    foreign = media.create_asset(
        _uid(), foreign_org, "/m/b.png", "image/png", 10, NOW
    )
    video = media.create_asset(
        _uid(), org_id, "/m/c.mp4", "video/mp4", 10, NOW
    )
    with pytest.raises(NotFoundError):
        svc.create_post(
            org_id, owner, "discussion", "", "x", [foreign.asset_id]
        )
    with pytest.raises(NotFoundError):
        svc.create_post(
            org_id, owner, "discussion", "", "x", [video.asset_id]
        )
    snap = svc.create_post(
        org_id, owner, "discussion", "", "x", [good.asset_id]
    )
    assert [m.asset_id for m in snap.media] == [good.asset_id]
