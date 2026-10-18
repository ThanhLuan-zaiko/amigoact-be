"""In-memory chat ports for service unit tests.

Split from workspace_fakes.py for the 350-line rule; the shared NOW/_uid
helpers still live there.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from chat.attachments import ChatAttachments
from chat.interfaces import (
    AttachmentClaimStore,
    ChatEvents,
    ChatStore,
)
from tests.unit.org_fakes import FakeMedia, FakeStore
from tests.unit.workspace_fakes import NOW, _uid


class FakeChatStore(ChatStore, AttachmentClaimStore):
    """Room message rows, read pointers, dm rows, attachment claims."""

    def __init__(self) -> None:
        self.messages: list[Any] = []
        self.media: list[Any] = []
        self.media_authors: list[Any] = []
        self.reads: dict[tuple[UUID, UUID], Any] = {}
        self.dm_rooms: dict[tuple[UUID, UUID], Any] = {}
        self.dm_pairs: dict[tuple[UUID, UUID, UUID], Any] = {}
        self.claims: dict[UUID, Any] = {}

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

    def index_media(self, room_id, bucket, message_id, author_id, now,
                    items):  # noqa: ANN001, ANN202
        for item in items:
            self.media.append(
                SimpleNamespace(
                    room_id=room_id, bucket=bucket, kind=item.kind,
                    message_id=message_id, item_index=item.item_index,
                    author_id=author_id, media_id=item.media_id,
                    url=item.url, mime=item.mime, name=item.name,
                    size_bytes=item.size_bytes, created_at=now,
                )
            )
        pairs = {(item.kind, author_id) for item in items}
        for kind, uid in pairs:
            hit = next(
                (
                    row
                    for row in self.media_authors
                    if row.room_id == room_id
                    and row.kind == kind
                    and row.author_id == uid
                ),
                None,
            )
            if hit is not None:
                hit.last_at = now
            else:
                self.media_authors.append(
                    SimpleNamespace(
                        room_id=room_id, kind=kind,
                        author_id=uid, last_at=now,
                    )
                )

    def list_media_page(self, room_id, bucket, kind, upper, limit,
                        author_id=None):  # noqa: ANN001, ANN202
        rows = [
            row
            for row in self.media
            if row.room_id == room_id
            and row.bucket == bucket
            and row.kind == kind
            and (author_id is None or row.author_id == author_id)
            and (upper is None or row.message_id <= upper)
        ]
        rows.sort(key=lambda r: (r.message_id, r.item_index), reverse=True)
        return rows[:limit]

    def list_media_authors(self, room_id):  # noqa: ANN001, ANN202
        return [
            row for row in self.media_authors if row.room_id == room_id
        ]

    def delete_media_index(self, room_id, bucket, message_id,
                           kinds=None):  # noqa: ANN001, ANN202
        keep = set(kinds) if kinds is not None else None
        dropped = [
            row
            for row in self.media
            if row.room_id == room_id
            and row.bucket == bucket
            and row.message_id == message_id
            and (keep is None or row.kind in keep)
        ]
        doomed = {id(row) for row in dropped}
        self.media = [row for row in self.media if id(row) not in doomed]
        for kind, uid in {(r.kind, r.author_id) for r in dropped}:
            still = any(
                row.room_id == room_id
                and row.kind == kind
                and row.author_id == uid
                for row in self.media
            )
            if still:
                continue
            self.media_authors = [
                row
                for row in self.media_authors
                if not (
                    row.room_id == room_id
                    and row.kind == kind
                    and row.author_id == uid
                )
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
        self.pins[(room_id, message_id)] = SimpleNamespace(
            room_id=room_id, message_id=message_id,
            pinned_by=pinned_by, pinned_at=now,
        )

    def clear_pin(self, room_id, message_id):  # noqa: ANN001, ANN202
        getattr(self, "pins", {}).pop((room_id, message_id), None)

    def get_pin(self, room_id, message_id):  # noqa: ANN001, ANN202
        return getattr(self, "pins", {}).get((room_id, message_id))

    def list_pins(self, room_id):  # noqa: ANN001, ANN202
        return [
            p for p in getattr(self, "pins", {}).values()
            if p.room_id == room_id
        ]

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

    def list_reads(self, room_id):  # noqa: ANN001, ANN202
        return [
            row
            for (rid, _uid), row in self.reads.items()
            if rid == room_id
        ]

    def claim_attachment(self, media_id, room_id, message_id, now):  # noqa: ANN001, ANN202
        if media_id in self.claims:
            return False
        self.claims[media_id] = SimpleNamespace(
            media_id=media_id, room_id=room_id,
            message_id=message_id, created_at=now,
        )
        return True

    def claimed_attachment(self, media_id):  # noqa: ANN001, ANN202
        return self.claims.get(media_id)

    def release_attachment(self, media_id):  # noqa: ANN001, ANN202
        self.claims.pop(media_id, None)

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


def make_attachments(
    media: Any = None, claims: Any = None
) -> ChatAttachments:
    """ChatAttachments over in-memory metadata and bytes."""
    return ChatAttachments(
        media if media is not None else FakeMedia(),
        FakeStore(),
        claims if claims is not None else FakeChatStore(),
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


class FakeChatEvents(ChatEvents):
    """Records every room fan-out call."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.inbox: list[tuple] = []

    def message_changed(self, room_id, action, message_id, actor_id):  # noqa: ANN001, ANN202
        self.calls.append((room_id, action, message_id, actor_id))

    def inbox_changed(self, action, room_id, org_id, peer_ids=()):  # noqa: ANN001, ANN202
        self.inbox.append((action, room_id, org_id, tuple(peer_ids)))
