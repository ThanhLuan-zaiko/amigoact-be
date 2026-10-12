"""Unit tests for CommentService: threads, paging, moderation."""

from __future__ import annotations

from uuid import UUID

import pytest

from core.exceptions import ForbiddenError, NotFoundError
from posts.comments_service import CommentService
from posts.lifecycle_service import PostLifecycleService
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
    FakePostStore,
    _uid,
    add_org,
)


def _service():
    posts, comments = FakePostStore(), FakeCommentStore()
    orgs, members, users = FakeOrgs(), FakeMembers(), FakeUsers()
    access, media = FakeAccess(), FakeMedia()
    events = FakeBoardEvents()
    owner = _uid()
    org_id = add_org(orgs, members, users, owner)
    post_service = PostService(
        posts, comments, orgs, members, users, media, access, events,
    )
    service = CommentService(
        posts, comments, orgs, members, users, access, events
    )
    return (
        service, post_service, comments, orgs, members, users, access,
        events, org_id, owner,
    )


def _member(
    members: FakeMembers, users: FakeUsers, org_id: UUID,
    email: str = "mem@x.com",
) -> UUID:
    uid = _uid()
    users.add(uid, email, f"Name {email}")
    members.put(org_id, uid, "active", NOW)
    return uid


def _post(svc: PostService, org_id: UUID, author: UUID) -> UUID:
    return svc.create_post(
        org_id, author, "discussion", "", "body", []
    ).post_id


def test_member_adds_and_lists_comments_oldest_first() -> None:
    (svc, posts_svc, comments, _, _, _, _, events, org_id,
     owner) = _service()
    post_id = _post(posts_svc, org_id, owner)
    first = svc.add_comment(org_id, post_id, owner, "one")
    second = svc.add_comment(org_id, post_id, owner, "two")
    assert comments.count(post_id) == 2
    page = svc.list_comments(org_id, post_id, owner)
    assert [c.comment_id for c in page.items] == [
        first.comment_id, second.comment_id
    ]
    assert page.items[0].author_name == "Owner"
    assert page.next_cursor is None
    assert events.calls[-1][1] == "comment.created"


def test_comment_pagination_cursor() -> None:
    svc, posts_svc, _, _, _, _, _, _, org_id, owner = _service()
    post_id = _post(posts_svc, org_id, owner)
    ids = [
        svc.add_comment(org_id, post_id, owner, f"c{i}").comment_id
        for i in range(3)
    ]
    page = svc.list_comments(org_id, post_id, owner, limit=2)
    assert [c.comment_id for c in page.items] == ids[:2]
    rest = svc.list_comments(
        org_id, post_id, owner, limit=2, cursor=page.next_cursor
    )
    assert [c.comment_id for c in rest.items] == ids[2:]
    assert rest.next_cursor is None


def test_comment_delete_author_manager_and_denied() -> None:
    (svc, posts_svc, comments, _, members, users, access, _,
     org_id, owner) = _service()
    member = _member(members, users, org_id)
    manager = _member(members, users, org_id, "mgr@x.com")
    access.perms[(org_id, manager)] = {"post:manage"}
    post_id = _post(posts_svc, org_id, owner)
    comment = svc.add_comment(org_id, post_id, owner, "x")
    with pytest.raises(ForbiddenError):
        svc.delete_comment(org_id, post_id, comment.comment_id, member)
    svc.delete_comment(org_id, post_id, comment.comment_id, manager)
    assert comments.count(post_id) == 0
    own = svc.add_comment(org_id, post_id, member, "mine")
    svc.delete_comment(org_id, post_id, own.comment_id, member)
    assert comments.count(post_id) == 0


def test_comment_guards() -> None:
    (svc, posts_svc, _, _, members, users, _, _, org_id,
     owner) = _service()
    outsider = _uid()
    post_id = _post(posts_svc, org_id, owner)
    with pytest.raises(NotFoundError):
        svc.add_comment(org_id, _uid(), owner, "x")  # ghost post
    with pytest.raises(ForbiddenError):
        svc.add_comment(org_id, post_id, outsider, "x")
    with pytest.raises(ForbiddenError):
        svc.list_comments(org_id, post_id, outsider)
    with pytest.raises(NotFoundError):
        svc.delete_comment(org_id, post_id, _uid(), owner)


def test_soft_delete_keeps_thread_hard_delete_wipes_it() -> None:
    (svc, posts_svc, comments, orgs, members, users, access, events,
     org_id, owner) = _service()
    lifecycle = PostLifecycleService(
        posts_svc._posts, comments, orgs, members, users, FakeMedia(),
        access, events,
    )
    post_id = _post(posts_svc, org_id, owner)
    svc.add_comment(org_id, post_id, owner, "gone soon")
    lifecycle.soft_delete(org_id, post_id, owner)
    assert comments.count(post_id) == 1  # trash keeps the thread
    with pytest.raises(NotFoundError):  # but trashed posts take no comments
        svc.add_comment(org_id, post_id, owner, "late")
    lifecycle.hard_delete(org_id, post_id, owner)
    assert comments.count(post_id) == 0
    assert comments.comments.get(post_id) in (None, [])
