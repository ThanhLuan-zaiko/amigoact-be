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
    body = columns.Text(required=True)
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
