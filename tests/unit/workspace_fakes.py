"""Shared in-memory ports for post/chat service unit tests."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import uuid_utils

from notifications.interfaces import NotificationPort
from posts.interfaces import (
    AnnouncementFeedEvents,
    CommentStore,
    PostEvents,
)
from tests.unit.post_fakes import FakePostStore  # noqa: F401 - re-export
from tests.unit.member_fakes import (
    FakeAccess,
    FakeMembers,
    FakeOrgs,
    FakeUsers,
)

NOW = datetime.now(timezone.utc)


def _uid() -> UUID:
    return UUID(str(uuid_utils.uuid7()))


def add_org(
    orgs: FakeOrgs,
    members: FakeMembers,
    users: FakeUsers,
    owner_id: UUID,
    name: str = "Org",
) -> UUID:
    """Live org with an active owner row plus a creation timestamp."""
    org_id = _uid()
    orgs.add(org_id, owner_id)
    orgs.orgs[org_id].created_at = NOW
    orgs.orgs[org_id].name = name
    members.put(org_id, owner_id, "active", NOW)
    users.add(owner_id, f"owner-{str(org_id)[:4]}@example.com", "Owner")
    return org_id


class FakeCommentStore(CommentStore):
    """Sorted comment partitions plus per-post totals."""

    def __init__(self) -> None:
        self.comments: dict[UUID, list[Any]] = {}
        self.counts: dict[UUID, int] = {}

    def add(self, post_id, comment_id, author_id, body, now):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            post_id=post_id, comment_id=comment_id,
            author_id=author_id, body=body, created_at=now,
        )
        rows = self.comments.setdefault(post_id, [])
        rows.append(row)
        rows.sort(key=lambda r: r.comment_id)
        self.counts[post_id] = self.counts.get(post_id, 0) + 1
        return row

    def get(self, post_id, comment_id):  # noqa: ANN001, ANN202
        return next(
            (
                row
                for row in self.comments.get(post_id, [])
                if row.comment_id == comment_id
            ),
            None,
        )

    def list_page(self, post_id, cursor, limit):  # noqa: ANN001, ANN202
        return [
            row
            for row in self.comments.get(post_id, [])
            if cursor is None or row.comment_id > cursor
        ][:limit]

    def remove(self, comment):  # noqa: ANN001, ANN202
        rows = self.comments.get(comment.post_id, [])
        self.comments[comment.post_id] = [
            row for row in rows if row.comment_id != comment.comment_id
        ]
        self.counts[comment.post_id] = max(
            0, self.counts.get(comment.post_id, 0) - 1
        )

    def remove_all(self, post_id):  # noqa: ANN001, ANN202
        self.comments.pop(post_id, None)
        self.counts.pop(post_id, None)

    def count(self, post_id):  # noqa: ANN001, ANN202
        return self.counts.get(post_id, 0)



class FakeBoardEvents(PostEvents):
    """Records every board fan-out call."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def feed_changed(self, org_id, action, post_id, actor_id, detail=None):  # noqa: ANN001, ANN202
        self.calls.append((org_id, action, post_id, actor_id, detail))


class FakeTimelineEvents(AnnouncementFeedEvents):
    """Records every public-timeline fan-out call."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def feed_changed(self, action, post_id, org_id):  # noqa: ANN001, ANN202
        self.calls.append((action, post_id, org_id))


class FakeNotify(NotificationPort):
    """Records every emitted in-app notification."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def notify(self, user_id, type, title, body="", data_json=None):  # noqa: ANN001, ANN002, ANN202
        self.calls.append((user_id, type, title, body, data_json))
