"""Shared in-memory ports for post/chat service unit tests."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import uuid_utils

from chat.interfaces import ChatEvents, ChatStore
from notifications.interfaces import NotificationPort
from posts.interfaces import CommentStore, PostEvents, PostStore
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


class FakePostStore(PostStore):
    """Canonical rows plus sorted feed/pin/media projections."""

    def __init__(self) -> None:
        self.posts: dict[UUID, Any] = {}
        self.feed: dict[UUID, list[UUID]] = {}
        self.pinned: dict[UUID, list[UUID]] = {}
        self.media: dict[UUID, list[Any]] = {}

    def create(self, post_id, org_id, author_id, kind, title, body, media_ids, now):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            post_id=post_id, org_id=org_id, author_id=author_id,
            kind=kind, title=title, body=body, status="active",
            pinned_at=None, edited_at=None,
            created_at=now, updated_at=now,
        )
        self.posts[post_id] = row
        feed = self.feed.setdefault(org_id, [])
        feed.append(post_id)
        feed.sort(reverse=True)
        self.media[post_id] = [
            SimpleNamespace(post_id=post_id, position=i, asset_id=a)
            for i, a in enumerate(media_ids)
        ]
        return row

    def get(self, post_id):  # noqa: ANN001, ANN202
        return self.posts.get(post_id)

    def list_feed(self, org_id, cursor, limit):  # noqa: ANN001, ANN202
        rows = self.feed.get(org_id, [])
        return [
            p for p in rows if cursor is None or p < cursor
        ][:limit]

    def list_pinned(self, org_id, limit=5):  # noqa: ANN001, ANN202
        return self.pinned.get(org_id, [])[:limit]

    def update_body(self, post, title, body, now):  # noqa: ANN001, ANN202
        post.title = title
        post.body = body
        post.edited_at = now
        post.updated_at = now

    def set_pinned(self, post, pinned_at, now):  # noqa: ANN001, ANN202
        post.pinned_at = pinned_at
        post.updated_at = now
        rows = self.pinned.setdefault(post.org_id, [])
        if pinned_at is None:
            if post.post_id in rows:
                rows.remove(post.post_id)
        elif post.post_id not in rows:
            rows.append(post.post_id)
            rows.sort(reverse=True)

    def delete(self, post):  # noqa: ANN001, ANN202
        self.posts.pop(post.post_id, None)
        if post.org_id in self.feed and post.post_id in self.feed[post.org_id]:
            self.feed[post.org_id].remove(post.post_id)
        if post.org_id in self.pinned and post.post_id in self.pinned[post.org_id]:
            self.pinned[post.org_id].remove(post.post_id)
        self.media.pop(post.post_id, None)

    def list_media(self, post_id):  # noqa: ANN001, ANN202
        return list(self.media.get(post_id, []))


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


class FakeChatStore(ChatStore):
    """Room message rows, read pointers, and dm room rows."""

    def __init__(self) -> None:
        self.messages: list[Any] = []
        self.reads: dict[tuple[UUID, UUID], Any] = {}
        self.dm_rooms: dict[tuple[UUID, UUID], Any] = {}
        self.dm_pairs: dict[tuple[UUID, UUID, UUID], Any] = {}

    def create(self, room_id, bucket, message_id, author_id, body, now):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            room_id=room_id, bucket=bucket, message_id=message_id,
            author_id=author_id, body=body, created_at=now,
        )
        self.messages.append(row)
        return row

    def get(self, room_id, bucket, message_id):  # noqa: ANN001, ANN202
        return next(
            (
                row
                for row in self.messages
                if row.room_id == room_id
                and row.bucket == bucket
                and row.message_id == message_id
            ),
            None,
        )

    def list_before(self, room_id, bucket, upper, limit):  # noqa: ANN001, ANN202
        rows = [
            row
            for row in self.messages
            if row.room_id == room_id
            and row.bucket == bucket
            and (upper is None or row.message_id < upper)
        ]
        rows.sort(key=lambda r: r.message_id, reverse=True)
        return rows[:limit]

    def count_after(self, room_id, bucket, lower):  # noqa: ANN001, ANN202
        return len(
            [
                row
                for row in self.messages
                if row.room_id == room_id
                and row.bucket == bucket
                and (lower is None or row.message_id > lower)
            ]
        )

    def delete(self, message):  # noqa: ANN001, ANN202
        self.messages = [
            row for row in self.messages if row is not message
        ]

    def get_read(self, room_id, user_id):  # noqa: ANN001, ANN202
        return self.reads.get((room_id, user_id))

    def mark_read(self, room_id, user_id, message_id, now):  # noqa: ANN001, ANN202
        self.reads[(room_id, user_id)] = SimpleNamespace(
            room_id=room_id, user_id=user_id,
            last_read_message_id=message_id, last_read_at=now,
        )

    def get_dm_room(self, user_id, room_id):  # noqa: ANN001, ANN202
        return self.dm_rooms.get((user_id, room_id))

    def list_dm_rooms(self, user_id):  # noqa: ANN001, ANN202
        return [
            row
            for (uid, _rid), row in self.dm_rooms.items()
            if uid == user_id
        ]

    def find_dm_pair(self, org_id, user_lo, user_hi):  # noqa: ANN001, ANN202
        return self.dm_pairs.get((org_id, user_lo, user_hi))

    def create_dm_room(self, room_id, org_id, user_lo, user_hi, now):  # noqa: ANN001, ANN202
        pair = self.dm_pairs.get((org_id, user_lo, user_hi))
        if pair is None:
            pair = SimpleNamespace(
                org_id=org_id, user_lo=user_lo, user_hi=user_hi,
                room_id=room_id, created_at=now,
            )
            self.dm_pairs[(org_id, user_lo, user_hi)] = pair
        for user, peer in ((user_lo, user_hi), (user_hi, user_lo)):
            self.dm_rooms[(user, pair.room_id)] = SimpleNamespace(
                user_id=user, room_id=pair.room_id, org_id=org_id,
                peer_id=peer, created_at=pair.created_at,
            )
        return pair


class FakeActivities:
    """Minimal ActivityLookup stand-in for room resolution."""

    def __init__(self) -> None:
        self.activities: dict[UUID, Any] = {}

    def add(self, activity_id: UUID, org_id: UUID) -> None:
        self.activities[activity_id] = SimpleNamespace(
            org_id=org_id, created_at=NOW
        )

    def get(self, activity_id):  # noqa: ANN001, ANN202
        return self.activities.get(activity_id)


class FakeBoardEvents(PostEvents):
    """Records every board fan-out call."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def feed_changed(self, org_id, action, post_id, actor_id, detail=None):  # noqa: ANN001, ANN202
        self.calls.append((org_id, action, post_id, actor_id, detail))


class FakeChatEvents(ChatEvents):
    """Records every room fan-out call."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def message_changed(self, room_id, action, message_id, actor_id):  # noqa: ANN001, ANN202
        self.calls.append((room_id, action, message_id, actor_id))


class FakeNotify(NotificationPort):
    """Records every emitted in-app notification."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def notify(self, user_id, type, title, body="", data_json=None):  # noqa: ANN001, ANN002, ANN202
        self.calls.append((user_id, type, title, body, data_json))
