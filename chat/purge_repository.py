"""cqlengine purge of one room's message tables (event hard delete).

Every delete addresses a full partition or a known primary key, so the
wipe never needs ALLOW FILTERING. Reads page by clustering key because
cqlengine caps an unbounded query at 10k rows.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from chat.helpers import MEDIA_KINDS
from chat.interfaces import RoomPurgeStore
from chat.model import (
    OrgRoomMedia,
    OrgRoomMediaAuthor,
    OrgRoomMediaByAuthor,
    OrgRoomMessage,
    OrgRoomPinV2,
    OrgRoomReaction,
    OrgRoomRead,
)

PURGE_PAGE = 500


class CqlRoomPurgeStore(RoomPurgeStore):
    """Partition-level deletes over the org_room_* tables."""

    def purge_room(self, room_id: UUID, buckets: Iterable[str]) -> list[str]:
        blobs: list[str] = []
        for bucket in buckets:
            last: UUID | None = None
            while True:
                query = OrgRoomMessage.objects(room_id=room_id, bucket=bucket)
                if last is not None:
                    query = query.filter(message_id__gt=last)
                page = list(query.limit(PURGE_PAGE))
                for row in page:
                    if row.attachments_json:
                        blobs.append(row.attachments_json)
                    OrgRoomReaction.objects(
                        room_id=room_id, message_id=row.message_id
                    ).delete()
                if len(page) < PURGE_PAGE:
                    break
                last = page[-1].message_id
            OrgRoomMessage.objects(room_id=room_id, bucket=bucket).delete()
            for kind in MEDIA_KINDS:
                OrgRoomMedia.objects(
                    room_id=room_id, bucket=bucket, kind=kind
                ).delete()
        for author in OrgRoomMediaAuthor.objects(room_id=room_id).all():
            OrgRoomMediaByAuthor.objects(
                room_id=room_id, kind=author.kind, author_id=author.author_id
            ).delete()
        OrgRoomMediaAuthor.objects(room_id=room_id).delete()
        OrgRoomPinV2.objects(room_id=room_id).delete()
        OrgRoomRead.objects(room_id=room_id).delete()
        return blobs
