"""cqlengine models for the chat bounded context (persistence only).

A room id is the org id (general room), an activity id (activity room),
or a generated dm room id (channel chat:{room_id}). Messages partition by
(room_id, YYYYMM bucket) and cluster by their UUIDv7 id, so id order
equals time order and the id doubles as the history cursor (schemas.cql
section 16).
"""

from __future__ import annotations

import core.database  # noqa: F401  (reactor compat shim must run first)
from core.ids import uuid7
from cassandra.cqlengine import columns, models


class OrgRoomMessage(models.Model):
    """One chat message inside its room+month partition."""

    __table_name__ = "org_room_messages"
    __keyspace__ = "amigoact"

    room_id = columns.UUID(primary_key=True, partition_key=True)
    bucket = columns.Text(primary_key=True, partition_key=True)
    message_id = columns.UUID(
        primary_key=True, clustering_order="ASC", default=uuid7
    )
    author_id = columns.UUID(required=True)
    # required=False: attachment-only messages store an empty body.
    body = columns.Text(required=False)
    # Denormalized reply preview: the target lives in another month
    # bucket, so the row carries its own author/body snippet.
    reply_to_id = columns.UUID(required=False)
    reply_to_author = columns.Text(required=False)
    reply_to_body = columns.Text(required=False)
    edited_at = columns.DateTime(required=False)
    # JSON list of {media_id, file_url, mime, name, size_bytes}.
    attachments_json = columns.Text(required=False)
    # JSON list of {id, name}: members @-mentioned inside this message.
    mentions_json = columns.Text(required=False)
    created_at = columns.DateTime(required=True)


class OrgRoomReaction(models.Model):
    """One user's emoji reaction; toggling removes the (emoji,user) pair."""

    __table_name__ = "org_room_reactions"
    __keyspace__ = "amigoact"

    room_id = columns.UUID(primary_key=True, partition_key=True)
    message_id = columns.UUID(primary_key=True, partition_key=True)
    emoji = columns.Text(primary_key=True, clustering_order="ASC")
    user_id = columns.UUID(primary_key=True, clustering_order="ASC")
    created_at = columns.DateTime(required=True)


class OrgRoomPin(models.Model):
    """The room's pinned message slot (one pin per room, latest wins)."""

    __table_name__ = "org_room_pins"
    __keyspace__ = "amigoact"

    room_id = columns.UUID(primary_key=True)
    message_id = columns.UUID(required=True)
    pinned_by = columns.UUID(required=True)
    pinned_at = columns.DateTime(required=True)


class OrgRoomMute(models.Model):
    """Per-user mute flag of one room; muted rooms still list but dim."""

    __table_name__ = "org_room_mutes"
    __keyspace__ = "amigoact"

    user_id = columns.UUID(primary_key=True, partition_key=True)
    room_id = columns.UUID(primary_key=True, clustering_order="ASC")
    created_at = columns.DateTime(required=True)


class OrgRoomRead(models.Model):
    """Per-member read pointer of one room for the unread badge."""

    __table_name__ = "org_room_reads"
    __keyspace__ = "amigoact"

    room_id = columns.UUID(primary_key=True, partition_key=True)
    user_id = columns.UUID(primary_key=True, clustering_order="ASC")
    last_read_message_id = columns.UUID(required=False)
    last_read_at = columns.DateTime(required=False)


class OrgDmPair(models.Model):
    """Canonical dm pair -> room. user_lo < user_hi, claimed with LWT."""

    __table_name__ = "org_dm_pairs"
    __keyspace__ = "amigoact"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    user_lo = columns.UUID(primary_key=True, clustering_order="ASC")
    user_hi = columns.UUID(primary_key=True, clustering_order="ASC")
    room_id = columns.UUID(required=True)
    created_at = columns.DateTime(required=True)


class OrgDmRoom(models.Model):
    """One participant's dm inbox row (also the room ACL lookup)."""

    __table_name__ = "org_dm_rooms"
    __keyspace__ = "amigoact"

    user_id = columns.UUID(primary_key=True, partition_key=True)
    room_id = columns.UUID(primary_key=True, clustering_order="ASC")
    org_id = columns.UUID(required=True)
    peer_id = columns.UUID(required=True)
    created_at = columns.DateTime(required=True)
