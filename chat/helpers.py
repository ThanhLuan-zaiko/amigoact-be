"""Month-bucket helpers for the chat partition walk."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from chat.dtos import (
    AttachmentBrief,
    ChatMessageSnapshot,
    MentionBrief,
    ReactionTally,
)
from core.security import utc_aware

# A page or preview scans back at most this many month buckets; deeper
# history keeps a resume cursor instead of one slow request. Unread
# counts cap here too.
MAX_SCAN_BUCKETS = 6
UNREAD_CAP = 99


def bucket_of(moment: datetime) -> str:
    """'YYYYMM' partition bucket of a timestamp (UTC)."""
    stamp = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).strftime("%Y%m")


def bucket_of_uuid(value: UUID) -> str:
    """Bucket of a UUIDv7 id: its leading 48 bits are unix milliseconds."""
    ms = int.from_bytes(value.bytes[:6], "big")
    return bucket_of(datetime.fromtimestamp(ms / 1000, tz=timezone.utc))


def prev_bucket(bucket: str) -> str:
    """Previous 'YYYYMM' step."""
    year, month = int(bucket[:4]), int(bucket[4:6])
    month -= 1
    if month == 0:
        year, month = year - 1, 12
    return f"{year:04d}{month:02d}"


def next_bucket(bucket: str) -> str:
    """Following 'YYYYMM' step."""
    year, month = int(bucket[:4]), int(bucket[4:6])
    month += 1
    if month == 13:
        year, month = year + 1, 1
    return f"{year:04d}{month:02d}"


def unread_count(store, room_id: UUID, floor: str, last_read) -> int:  # noqa: ANN001, ANN202
    """Messages newer than the read pointer, capped at UNREAD_CAP.

    Only the first scanned bucket counts from the pointer; buckets after
    it count whole. The walk stops at `floor` (room creation month) and
    at the current month either way.
    """
    start = bucket_of_uuid(last_read) if last_read is not None else floor
    current = bucket_of(datetime.now(timezone.utc))
    bucket, total = start, 0
    while bucket <= current and total < UNREAD_CAP:
        total += store.count_after(room_id, bucket, last_read)
        last_read = None  # only the first bucket counts from the pointer
        bucket = next_bucket(bucket)
    return min(total, UNREAD_CAP)


def peek_last_message(store, room_id: UUID, floor: str):  # noqa: ANN001, ANN202
    """Newest message row, walking back at most MAX_SCAN_BUCKETS.

    Rooms silent for longer than the scan depth report None and settle
    by their own creation date at the bottom of the inbox.
    """
    bucket = bucket_of(datetime.now(timezone.utc))
    for _ in range(MAX_SCAN_BUCKETS):
        rows = store.list_before(room_id, bucket, None, 1)
        if rows:
            return rows[0]
        if bucket <= floor:
            break
        bucket = prev_bucket(bucket)
    return None


# Quoted reply previews stay single-line; the full body is one jump away.
REPLY_PREVIEW_LEN = 140
# One message carries at most this many attachment blocks.
MAX_ATTACHMENTS = 4


def encode_attachments(items: list[AttachmentBrief]) -> str:
    """Pack the embedded attachment list for the JSON text column."""
    return json.dumps(
        [
            {
                "media_id": str(item.media_id),
                "url": item.url,
                "mime": item.mime,
                "name": item.name,
                "size_bytes": item.size_bytes,
            }
            for item in items
        ]
    )


def decode_attachments(raw: str | None) -> tuple[AttachmentBrief, ...]:
    """Unpack the stored JSON list; malformed rows read as empty."""
    if not raw:
        return ()
    try:
        items = json.loads(raw)
    except ValueError:
        return ()
    out: list[AttachmentBrief] = []
    for item in items if isinstance(items, list) else []:
        try:
            out.append(
                AttachmentBrief(
                    media_id=UUID(str(item["media_id"])),
                    url=str(item.get("url") or ""),
                    mime=str(item.get("mime") or ""),
                    name=str(item.get("name") or ""),
                    size_bytes=int(item.get("size_bytes") or 0),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(out)


# Reactions are limited to a fixed palette so tallies stay readable.
REACTION_EMOJIS = frozenset({"👍", "❤️", "😂", "😮", "😢", "😡"})
# Mentions cap protects the members scan from degenerate bodies.
MAX_MENTIONS = 10


def encode_mentions(items: list[MentionBrief]) -> str:
    """Pack mention tuples for the JSON text column."""
    return json.dumps(
        [{"id": str(item.user_id), "name": item.name} for item in items]
    )


def decode_mentions(raw: str | None) -> tuple[MentionBrief, ...]:
    """Unpack stored mentions; malformed rows read as empty."""
    if not raw:
        return ()
    try:
        items = json.loads(raw)
    except ValueError:
        return ()
    out: list[MentionBrief] = []
    for item in items if isinstance(items, list) else []:
        try:
            out.append(
                MentionBrief(
                    user_id=UUID(str(item["id"])),
                    name=str(item.get("name") or ""),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(out)


def tally_reactions(rows, viewer_id: UUID | None):  # noqa: ANN001, ANN202
    """Group reaction rows into per-emoji counts plus the `mine` flag."""
    counts: dict[str, list] = {}
    order: list[str] = []
    for row in rows:
        if row.emoji not in counts:
            counts[row.emoji] = []
            order.append(row.emoji)
        counts[row.emoji].append(row.user_id)
    return tuple(
        ReactionTally(
            emoji=emoji,
            count=len(counts[emoji]),
            mine=viewer_id is not None and viewer_id in counts[emoji],
        )
        for emoji in order
    )


def message_snapshot(
    users,  # noqa: ANN001
    row,  # noqa: ANN001
    cipher=None,  # noqa: ANN001
    reactions=(),  # noqa: ANN001
):  # noqa: ANN202
    """Shared row -> DTO join used by the read and write services.

    `cipher` decrypts body + reply preview; without it rows read as
    stored (callers that never see ciphertext may omit it).
    """
    decrypt = cipher.decrypt if cipher is not None else (lambda v: v or "")
    brief = users.get_brief(row.author_id)
    return ChatMessageSnapshot(
        message_id=row.message_id,
        room_id=row.room_id,
        author_id=row.author_id,
        author_name=brief.full_name if brief else "Unknown user",
        body=decrypt(row.body),
        created_at=utc_aware(row.created_at),
        reply_to_id=getattr(row, "reply_to_id", None),
        reply_to_author=getattr(row, "reply_to_author", None),
        reply_to_body=decrypt(getattr(row, "reply_to_body", None)) or None,
        edited_at=utc_aware(getattr(row, "edited_at", None)),
        attachments=decode_attachments(
            getattr(row, "attachments_json", None)
        ),
        reactions=tuple(reactions),
        mentions=decode_mentions(getattr(row, "mentions_json", None)),
    )
