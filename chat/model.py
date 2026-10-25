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


class OrgRoomMedia(models.Model):
    """Shared-item index of a room for the info panel's media tabs.

    One row per attachment or extracted link, keyed like the message's
    own (room_id, 'YYYYMM') bucket plus a kind sub-partition so each tab
    reads one partition without ALLOW FILTERING. Rows are written on
    send (links re-indexed on edit) and dropped with the message.
    """

    __table_name__ = "org_room_media"

    room_id = columns.UUID(primary_key=True, partition_key=True)
    bucket = columns.Text(primary_key=True, partition_key=True)
    # 'image' | 'video' | 'file' | 'link' - one partition per tab kind.
    kind = columns.Text(primary_key=True, partition_key=True)
    message_id = columns.UUID(
        primary_key=True, clustering_order="ASC"
    )
    item_index = columns.Integer(
        primary_key=True, clustering_order="ASC"
    )
    author_id = columns.UUID(required=True)
    # Attachment rows only: the staged media asset id.
    media_id = columns.UUID(required=False)
    # Attachments store the /media/ path; links store ciphertext
    # ('v1gcm:' prefix) so the index never weakens body encryption.
    url = columns.Text(required=True)
    mime = columns.Text(required=False)
    name = columns.Text(required=False)
    size_bytes = columns.BigInt(required=False)
    created_at = columns.DateTime(required=True)


class OrgRoomMediaByAuthor(models.Model):
    """Author-scoped mirror of org_room_media for the sender filter.

    Same payload, partitioned by (room_id, kind, author_id) and
    clustered by (bucket, message_id, item_index): a sender-filtered
    tab still reads one partition while the month walk stays identical
    to the unfiltered path. Written and dropped together with the base
    index row.
    """

    __table_name__ = "org_room_media_by_author"

    room_id = columns.UUID(primary_key=True, partition_key=True)
    kind = columns.Text(primary_key=True, partition_key=True)
    author_id = columns.UUID(primary_key=True, partition_key=True)
    bucket = columns.Text(primary_key=True, clustering_order="ASC")
    message_id = columns.UUID(
        primary_key=True, clustering_order="ASC"
    )
    item_index = columns.Integer(
        primary_key=True, clustering_order="ASC"
    )
    media_id = columns.UUID(required=False)
    url = columns.Text(required=True)
    mime = columns.Text(required=False)
    name = columns.Text(required=False)
    size_bytes = columns.BigInt(required=False)
    created_at = columns.DateTime(required=True)


class OrgRoomMediaAuthor(models.Model):
    """One row per (room, kind, author) that ever shared, for the
    sender filter's option list. last_at refreshes on each index write;
    the row is dropped once no by-author item of the pair remains."""

    __table_name__ = "org_room_media_authors"

    room_id = columns.UUID(primary_key=True, partition_key=True)
    kind = columns.Text(primary_key=True, clustering_order="ASC")
    author_id = columns.UUID(primary_key=True, clustering_order="ASC")
    last_at = columns.DateTime(required=True)


class OrgChatAttachmentClaim(models.Model):
    """Single-use claim tying a staged chat file to exactly one message.

    A staged asset may only ever attach to one message: the LWT insert
    makes a second send fail instead of silently sharing the file and
    letting one delete wipe it for both. Rows are released when the
    message (or the uploader's staged chip) is discarded.
    """

    __table_name__ = "chat_attachment_claims"

    media_id = columns.UUID(primary_key=True)
    room_id = columns.UUID(required=True)
    message_id = columns.UUID(required=True)
    created_at = columns.DateTime(required=True)


class OrgRoomReaction(models.Model):
    """One user's emoji reaction; toggling removes the (emoji,user) pair."""

    __table_name__ = "org_room_reactions"

    room_id = columns.UUID(primary_key=True, partition_key=True)
    message_id = columns.UUID(primary_key=True, partition_key=True)
    emoji = columns.Text(primary_key=True, clustering_order="ASC")
    user_id = columns.UUID(primary_key=True, clustering_order="ASC")
    created_at = columns.DateTime(required=True)


class OrgRoomPinV2(models.Model):
    """One pinned message row; a room holds many pins, one per message.

    Partition key (room_id) lists every pin of a room; clustering on
    message_id makes pin/unpin a point write. Rows sort by pinned_at in
    the service (pin counts stay small). Replaces the legacy
    org_room_pins single-slot table (chat phase 6).
    """

    __table_name__ = "org_room_pins_v2"

    room_id = columns.UUID(primary_key=True, partition_key=True)
    message_id = columns.UUID(primary_key=True, clustering_order="ASC")
    pinned_by = columns.UUID(required=True)
    pinned_at = columns.DateTime(required=True)


class OrgRoomMute(models.Model):
    """Per-user mute flag of one room; muted rooms still list but dim."""

    __table_name__ = "org_room_mutes"

    user_id = columns.UUID(primary_key=True, partition_key=True)
    room_id = columns.UUID(primary_key=True, clustering_order="ASC")
    created_at = columns.DateTime(required=True)


class OrgRoomRead(models.Model):
    """Per-member read pointer of one room for the unread badge."""

    __table_name__ = "org_room_reads"

    room_id = columns.UUID(primary_key=True, partition_key=True)
    user_id = columns.UUID(primary_key=True, clustering_order="ASC")
    last_read_message_id = columns.UUID(required=False)
    last_read_at = columns.DateTime(required=False)


class OrgDmPair(models.Model):
    """Canonical dm pair -> room. user_lo < user_hi, claimed with LWT."""

    __table_name__ = "org_dm_pairs"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    user_lo = columns.UUID(primary_key=True, clustering_order="ASC")
    user_hi = columns.UUID(primary_key=True, clustering_order="ASC")
    room_id = columns.UUID(required=True)
    created_at = columns.DateTime(required=True)


class OrgDmRoom(models.Model):
    """One participant's dm inbox row (also the room ACL lookup)."""

    __table_name__ = "org_dm_rooms"

    user_id = columns.UUID(primary_key=True, partition_key=True)
    room_id = columns.UUID(primary_key=True, clustering_order="ASC")
    org_id = columns.UUID(required=True)
    peer_id = columns.UUID(required=True)
    created_at = columns.DateTime(required=True)


class OrgChatChannel(models.Model):
    """One named org channel; channel_id doubles as the room id.

    parent_room_id set makes the row a sub-thread of that room (the
    general room or a top-level channel); activity_id optionally links
    the thread to one org activity.
    """

    __table_name__ = "org_chat_channels"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    channel_id = columns.UUID(
        primary_key=True, clustering_order="ASC", default=uuid7
    )
    name = columns.Text(required=True)
    # Casefolded name for the uniqueness claim and search.
    name_folded = columns.Text(required=True)
    topic = columns.Text(required=False)
    # "text" | "report" | "task" - display semantics only.
    kind = columns.Text(required=True)
    # "everyone" | "managers" - who may post.
    post_policy = columns.Text(required=True)
    # "org" (every member) | "restricted" (roster below).
    visibility = columns.Text(required=True)
    # Sub-threads: the room this channel hangs under (None on top-level
    # channels). Threads never nest: a thread's parent is never itself
    # a thread.
    parent_room_id = columns.UUID(required=False)
    # Optional activity the thread was opened for (display link only).
    activity_id = columns.UUID(required=False)
    created_by = columns.UUID(required=True)
    created_at = columns.DateTime(required=True)
    archived_at = columns.DateTime(required=False)
    archived_by = columns.UUID(required=False)


class OrgChatChannelById(models.Model):
    """channel_id -> full row mirror for room resolution lookups."""

    __table_name__ = "org_chat_channels_by_id"

    channel_id = columns.UUID(primary_key=True)
    org_id = columns.UUID(required=True)
    name = columns.Text(required=True)
    name_folded = columns.Text(required=True)
    topic = columns.Text(required=False)
    kind = columns.Text(required=True)
    post_policy = columns.Text(required=True)
    visibility = columns.Text(required=True)
    parent_room_id = columns.UUID(required=False)
    activity_id = columns.UUID(required=False)
    created_by = columns.UUID(required=True)
    created_at = columns.DateTime(required=True)
    archived_at = columns.DateTime(required=False)
    archived_by = columns.UUID(required=False)


class OrgChatRoomThread(models.Model):
    """parent_room_id -> thread mirror for a room's sub-thread list.

    Same payload as the by-id row, partitioned so one room's threads
    read a single partition. Written/dropped alongside the two base
    channel rows in _write().
    """

    __table_name__ = "org_chat_room_threads"

    parent_room_id = columns.UUID(primary_key=True, partition_key=True)
    channel_id = columns.UUID(
        primary_key=True, clustering_order="ASC"
    )
    org_id = columns.UUID(required=True)
    name = columns.Text(required=True)
    name_folded = columns.Text(required=True)
    topic = columns.Text(required=False)
    kind = columns.Text(required=True)
    post_policy = columns.Text(required=True)
    visibility = columns.Text(required=True)
    activity_id = columns.UUID(required=False)
    created_by = columns.UUID(required=True)
    created_at = columns.DateTime(required=True)
    archived_at = columns.DateTime(required=False)
    archived_by = columns.UUID(required=False)


class OrgChatChannelName(models.Model):
    """LWT claim making one live channel name unique per org."""

    __table_name__ = "org_chat_channel_names"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    name_folded = columns.Text(primary_key=True, clustering_order="ASC")
    channel_id = columns.UUID(required=True)
    created_at = columns.DateTime(required=True)


class OrgChatChannelMember(models.Model):
    """Restricted-channel roster row: who may open the room."""

    __table_name__ = "org_chat_channel_members"

    channel_id = columns.UUID(primary_key=True, partition_key=True)
    user_id = columns.UUID(primary_key=True, clustering_order="ASC")
    added_by = columns.UUID(required=True)
    added_at = columns.DateTime(required=True)


class OrgChatChannelMembership(models.Model):
    """Per-user restricted-channel index for inbox enumeration."""

    __table_name__ = "org_chat_channel_memberships"

    user_id = columns.UUID(primary_key=True, partition_key=True)
    channel_id = columns.UUID(primary_key=True, clustering_order="ASC")
    org_id = columns.UUID(required=True)
    added_at = columns.DateTime(required=True)
