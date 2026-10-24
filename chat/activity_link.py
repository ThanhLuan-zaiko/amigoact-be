"""Chat consequences of the activity trash lifecycle.

Soft delete freezes chat at read time (rooms.require_live_activity), so
trash and restore only nudge inboxes. A hard delete wipes the event's
own room (room_id == activity_id) and archives every sub-thread linked
to the event, keeping its history readable for managers.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from activities.interfaces import ActivityChatLink
from chat.attachments import ChatAttachments
from chat.channel_interfaces import ChannelStore
from chat.helpers import bucket_of, decode_attachments, next_bucket
from chat.interfaces import ChatEvents, RoomPurgeStore
from chat.rooms import emit_inbox
from core.security import utcnow


def month_buckets(start: datetime | None, end: datetime) -> list[str]:
    """Every 'YYYYMM' bucket from start's month through end's month."""
    last = bucket_of(end)
    bucket = bucket_of(start) if start is not None else last
    out = [bucket]
    while bucket < last:
        bucket = next_bucket(bucket)
        out.append(bucket)
    return out


class ChatActivityLink(ActivityChatLink):
    """Purges the event room and archives event-linked threads."""

    def __init__(
        self,
        purge: RoomPurgeStore,
        channels: ChannelStore,
        events: ChatEvents,
        attachments: ChatAttachments | None = None,
    ) -> None:
        self._purge = purge
        self._channels = channels
        self._events = events
        self._attachments = attachments

    def _linked_threads(self, org_id: UUID, activity_id: UUID):  # noqa: ANN202
        return [
            row
            for row in self._channels.list_channels(org_id)
            if getattr(row, "activity_id", None) == activity_id
        ]

    def activity_changed(self, org_id: UUID, activity_id: UUID) -> None:
        emit_inbox(self._events, "room.updated", activity_id, org_id)
        for row in self._linked_threads(org_id, activity_id):
            emit_inbox(
                self._events, "channel.updated", row.channel_id, org_id
            )

    def activity_purged(
        self,
        org_id: UUID,
        activity_id: UUID,
        created_at: datetime | None,
        actor_id: UUID,
    ) -> None:
        now = utcnow()
        blobs = self._purge.purge_room(
            activity_id, month_buckets(created_at, now)
        )
        if self._attachments is not None:
            for blob in blobs:
                self._attachments.discard(
                    activity_id, decode_attachments(blob)
                )
        for row in self._linked_threads(org_id, activity_id):
            if row.archived_at is None:
                row.archived_at, row.archived_by = now, actor_id
                self._channels.update_channel(row)
                self._channels.release_name(
                    row.parent_room_id or row.org_id, row.name_folded
                )
            emit_inbox(
                self._events, "channel.updated", row.channel_id, org_id
            )
        emit_inbox(self._events, "room.deleted", activity_id, org_id)
