"""Shared in-memory ports for post/chat service unit tests."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import uuid_utils

from chat.interfaces import ChatEvents, ChatStore
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


class FakeChatStore(ChatStore):
    """Room message rows, read pointers, and dm room rows."""

    def __init__(self) -> None:
        self.messages: list[Any] = []
        self.reads: dict[tuple[UUID, UUID], Any] = {}
        self.dm_rooms: dict[tuple[UUID, UUID], Any] = {}
        self.dm_pairs: dict[tuple[UUID, UUID, UUID], Any] = {}

    def create(self, room_id, bucket, message_id, author_id, body, now,
               reply_to_id=None, reply_to_author=None, reply_to_body=None,
               attachments_json=None, mentions_json=None):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            room_id=room_id, bucket=bucket, message_id=message_id,
            author_id=author_id, body=body, created_at=now,
            reply_to_id=reply_to_id, reply_to_author=reply_to_author,
            reply_to_body=reply_to_body, edited_at=None,
            attachments_json=attachments_json,
            mentions_json=mentions_json,
        )
        self.messages.append(row)
        return row

    def update(self, message, body, now, mentions_json=None):  # noqa: ANN001, ANN202
        message.body = body
        message.edited_at = now
        message.mentions_json = mentions_json or None

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

    def set_reaction(self, room_id, message_id, user_id, emoji, now):  # noqa: ANN001, ANN202
        self.reactions = getattr(self, "reactions", None) or []
        hit = next(
            (
                r for r in self.reactions
                if r.room_id == room_id and r.message_id == message_id
                and r.user_id == user_id and r.emoji == emoji
            ),
            None,
        )
        if hit is not None:
            self.reactions.remove(hit)
            return False
        self.reactions.append(
            SimpleNamespace(
                room_id=room_id, message_id=message_id,
                user_id=user_id, emoji=emoji, created_at=now,
            )
        )
        return True

    def list_reactions(self, room_id, message_id):  # noqa: ANN001, ANN202
        return [
            r for r in getattr(self, "reactions", None) or []
            if r.room_id == room_id and r.message_id == message_id
        ]

    def set_pin(self, room_id, message_id, pinned_by, now):  # noqa: ANN001, ANN202
        self.pins = getattr(self, "pins", None) or {}
        self.pins[room_id] = SimpleNamespace(
            room_id=room_id, message_id=message_id,
            pinned_by=pinned_by, pinned_at=now,
        )

    def clear_pin(self, room_id):  # noqa: ANN001, ANN202
        getattr(self, "pins", {}).pop(room_id, None)

    def get_pin(self, room_id):  # noqa: ANN001, ANN202
        return getattr(self, "pins", {}).get(room_id)

    def set_mute(self, user_id, room_id, now):  # noqa: ANN001, ANN202
        self.mutes = getattr(self, "mutes", None) or {}
        self.mutes[(user_id, room_id)] = SimpleNamespace(
            user_id=user_id, room_id=room_id, created_at=now,
        )

    def clear_mute(self, user_id, room_id):  # noqa: ANN001, ANN202
        getattr(self, "mutes", {}).pop((user_id, room_id), None)

    def list_mutes(self, user_id):  # noqa: ANN001, ANN202
        return [
            row for key, row in getattr(self, "mutes", {}).items()
            if key[0] == user_id
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


class FakeUploader:
    """MediaUploader port: records calls, returns a canned snapshot."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def upload_media(self, org_id, user_id, filename, mime, content,
                     role="gallery"):  # noqa: ANN001, ANN202
        media_id = _uid()
        self.calls.append((org_id, user_id, filename, mime, role))
        return SimpleNamespace(
            id=media_id, org_id=org_id,
            file_url=f"/media/orgs/{org_id}/{media_id}.bin",
            mime=mime, size_bytes=len(content),
            original_name=filename,
        )


class FakeActivities:
    """Minimal ActivityLookup stand-in for room resolution."""

    def __init__(self) -> None:
        self.activities: dict[UUID, Any] = {}

    def add(
        self, activity_id: UUID, org_id: UUID, title: str = "Activity"
    ) -> None:
        self.activities[activity_id] = SimpleNamespace(
            id=activity_id, org_id=org_id, title=title, created_at=NOW
        )

    def get(self, activity_id):  # noqa: ANN001, ANN202
        return self.activities.get(activity_id)

    def list_by_org(self, org_id, limit=50):  # noqa: ANN001, ANN202
        return [
            row
            for row in self.activities.values()
            if row.org_id == org_id
        ][:limit]


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


class FakeChatEvents(ChatEvents):
    """Records every room fan-out call."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.inbox: list[tuple] = []

    def message_changed(self, room_id, action, message_id, actor_id):  # noqa: ANN001, ANN202
        self.calls.append((room_id, action, message_id, actor_id))

    def inbox_changed(self, action, room_id, org_id, peer_ids=()):  # noqa: ANN001, ANN202
        self.inbox.append((action, room_id, org_id, tuple(peer_ids)))


class FakeNotify(NotificationPort):
    """Records every emitted in-app notification."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def notify(self, user_id, type, title, body="", data_json=None):  # noqa: ANN001, ANN002, ANN202
        self.calls.append((user_id, type, title, body, data_json))
