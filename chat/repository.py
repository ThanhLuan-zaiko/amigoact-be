"""cqlengine persistence for org chat rooms and read pointers.

The dm pair claim uses raw CQL LWT because cqlengine cannot surface IF
NOT EXISTS results (same justification as the slug claims elsewhere).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from uuid import UUID


from chat.dtos import SharedItemDraft
from chat.helpers import MEDIA_KINDS
from chat.interfaces import ChatStore
from chat.model import (
    OrgDmPair,
    OrgDmRoom,
    OrgRoomMedia,
    OrgRoomMediaAuthor,
    OrgRoomMediaByAuthor,
    OrgRoomMessage,
    OrgRoomMute,
    OrgRoomPinV2,
    OrgRoomReaction,
    OrgRoomRead,
)
from core.cql import run as cql_run


class CqlChatStore(ChatStore):
    """Room message partitions, read pointers, and dm room rows."""

    def __init__(self, keyspace: str) -> None:
        self._keyspace = keyspace

    def create(
        self,
        room_id: UUID,
        bucket: str,
        message_id: UUID,
        author_id: UUID,
        body: str,
        now: datetime,
        reply_to_id: UUID | None = None,
        reply_to_author: str | None = None,
        reply_to_body: str | None = None,
        attachments_json: str | None = None,
        mentions_json: str | None = None,
    ) -> OrgRoomMessage:
        return OrgRoomMessage.create(
            room_id=room_id,
            bucket=bucket,
            message_id=message_id,
            author_id=author_id,
            body=body,
            reply_to_id=reply_to_id,
            reply_to_author=reply_to_author,
            reply_to_body=reply_to_body,
            attachments_json=attachments_json,
            mentions_json=mentions_json,
            created_at=now,
        )

    def update(
        self,
        message: OrgRoomMessage,
        body: str,
        now: datetime,
        mentions_json: str | None = None,
    ) -> None:
        OrgRoomMessage.objects(
            room_id=message.room_id,
            bucket=message.bucket,
            message_id=message.message_id,
        ).update(body=body, edited_at=now, mentions_json=mentions_json or None)

    def get(
        self, room_id: UUID, bucket: str, message_id: UUID
    ) -> OrgRoomMessage | None:
        return OrgRoomMessage.objects(
            room_id=room_id, bucket=bucket, message_id=message_id
        ).first()

    def list_before(
        self, room_id: UUID, bucket: str, upper: UUID | None, limit: int
    ) -> list[OrgRoomMessage]:
        query = OrgRoomMessage.objects(room_id=room_id, bucket=bucket)
        if upper is not None:
            query = query.filter(message_id__lt=upper)
        return list(query.order_by("-message_id").limit(limit))

    def count_after(
        self, room_id: UUID, bucket: str, lower: UUID | None
    ) -> int:
        query = OrgRoomMessage.objects(room_id=room_id, bucket=bucket)
        if lower is not None:
            query = query.filter(message_id__gt=lower)
        return int(query.count())

    def delete(self, message: OrgRoomMessage) -> None:
        OrgRoomMessage.objects(
            room_id=message.room_id,
            bucket=message.bucket,
            message_id=message.message_id,
        ).delete()

    def index_media(
        self,
        room_id: UUID,
        bucket: str,
        message_id: UUID,
        author_id: UUID,
        now: datetime,
        items: Iterable[SharedItemDraft],
    ) -> None:
        seen_authors: set[str] = set()
        for item in items:
            payload = dict(
                media_id=item.media_id,
                url=item.url,
                mime=item.mime or None,
                name=item.name or None,
                size_bytes=item.size_bytes or None,
                created_at=now,
            )
            OrgRoomMedia.create(
                room_id=room_id,
                bucket=bucket,
                kind=item.kind,
                message_id=message_id,
                item_index=item.item_index,
                author_id=author_id,
                **payload,
            )
            OrgRoomMediaByAuthor.create(
                room_id=room_id,
                kind=item.kind,
                author_id=author_id,
                bucket=bucket,
                message_id=message_id,
                item_index=item.item_index,
                **payload,
            )
            if item.kind not in seen_authors:
                seen_authors.add(item.kind)
                OrgRoomMediaAuthor.objects(
                    room_id=room_id, kind=item.kind, author_id=author_id
                ).update(last_at=now)

    def list_media_page(
        self,
        room_id: UUID,
        bucket: str,
        kind: str,
        upper: UUID | None,
        limit: int,
        author_id: UUID | None = None,
    ) -> list[OrgRoomMedia | OrgRoomMediaByAuthor]:
        if author_id is not None:
            # Sender filter: same month slice inside the author's own
            # (room, kind) partition; bucket equality frees ORDER BY on
            # the remaining clustering columns.
            query = OrgRoomMediaByAuthor.objects(
                room_id=room_id, kind=kind, author_id=author_id
            ).filter(bucket=bucket)
        else:
            query = OrgRoomMedia.objects(
                room_id=room_id, bucket=bucket, kind=kind
            )
        if upper is not None:
            # Inclusive bound: same-message rows left of the served
            # item_index are dropped by the service's cursor filter.
            query = query.filter(message_id__lte=upper)
        return list(
            query.order_by("-message_id", "-item_index").limit(limit)
        )

    def list_media_authors(
        self, room_id: UUID
    ) -> list[OrgRoomMediaAuthor]:
        return list(OrgRoomMediaAuthor.objects(room_id=room_id).all())

    def delete_media_index(
        self,
        room_id: UUID,
        bucket: str,
        message_id: UUID,
        kinds: Iterable[str] | None = None,
    ) -> None:
        # The by-author mirror and the presence row are keyed by
        # author_id, which the delete caller does not know: read the
        # doomed base rows first to learn every (kind, author) pair.
        removed: dict[tuple[str, UUID], list[OrgRoomMedia]] = {}
        for kind in tuple(kinds) if kinds is not None else MEDIA_KINDS:
            rows = list(
                OrgRoomMedia.objects(
                    room_id=room_id,
                    bucket=bucket,
                    kind=kind,
                    message_id=message_id,
                ).all()
            )
            for row in rows:
                removed.setdefault((kind, row.author_id), []).append(row)
        for (kind, author_id), rows in removed.items():
            for row in rows:
                row.delete()
                OrgRoomMediaByAuthor.objects(
                    room_id=room_id,
                    kind=kind,
                    author_id=author_id,
                    bucket=bucket,
                    message_id=row.message_id,
                    item_index=row.item_index,
                ).delete()
            # Presence row lives only while the author still owns at
            # least one item of that kind anywhere in the room.
            remaining = (
                OrgRoomMediaByAuthor.objects(
                    room_id=room_id, kind=kind, author_id=author_id
                )
                .limit(1)
                .first()
            )
            if remaining is None:
                OrgRoomMediaAuthor.objects(
                    room_id=room_id, kind=kind, author_id=author_id
                ).delete()

    def get_read(self, room_id: UUID, user_id: UUID) -> OrgRoomRead | None:
        return OrgRoomRead.objects(
            room_id=room_id, user_id=user_id
        ).first()

    def mark_read(
        self,
        room_id: UUID,
        user_id: UUID,
        message_id: UUID,
        now: datetime,
    ) -> None:
        OrgRoomRead.objects(room_id=room_id, user_id=user_id).update(
            last_read_message_id=message_id, last_read_at=now
        )

    def list_reads(self, room_id: UUID) -> list[OrgRoomRead]:
        return list(OrgRoomRead.objects(room_id=room_id).all())

    def set_reaction(
        self, room_id: UUID, message_id: UUID,
        user_id: UUID, emoji: str, now: datetime,
    ) -> bool:
        key = dict(
            room_id=room_id, message_id=message_id,
            emoji=emoji, user_id=user_id,
        )
        existing = OrgRoomReaction.objects(**key).first()
        if existing is not None:
            existing.delete()
            return False
        OrgRoomReaction.create(**key, created_at=now)
        return True

    def list_reactions(
        self, room_id: UUID, message_id: UUID
    ) -> list[OrgRoomReaction]:
        return list(
            OrgRoomReaction.objects(
                room_id=room_id, message_id=message_id).all()
        )

    def set_pin(
        self, room_id: UUID, message_id: UUID,
        pinned_by: UUID, now: datetime,
    ) -> None:
        OrgRoomPinV2.objects(
            room_id=room_id, message_id=message_id
        ).update(pinned_by=pinned_by, pinned_at=now)

    def clear_pin(self, room_id: UUID, message_id: UUID) -> None:
        OrgRoomPinV2.objects(
            room_id=room_id, message_id=message_id).delete()

    def get_pin(
        self, room_id: UUID, message_id: UUID
    ) -> OrgRoomPinV2 | None:
        return OrgRoomPinV2.objects(
            room_id=room_id, message_id=message_id).first()

    def list_pins(self, room_id: UUID) -> list[OrgRoomPinV2]:
        return list(OrgRoomPinV2.objects(room_id=room_id).all())

    def set_mute(self, user_id: UUID, room_id: UUID, now: datetime) -> None:
        OrgRoomMute.objects(user_id=user_id, room_id=room_id).update(
            created_at=now
        )

    def clear_mute(self, user_id: UUID, room_id: UUID) -> None:
        OrgRoomMute.objects(user_id=user_id, room_id=room_id).delete()

    def list_mutes(self, user_id: UUID) -> list[OrgRoomMute]:
        return list(OrgRoomMute.objects(user_id=user_id).all())

    def get_dm_room(self, user_id: UUID, room_id: UUID) -> OrgDmRoom | None:
        return OrgDmRoom.objects(
            user_id=user_id, room_id=room_id
        ).first()

    def list_dm_rooms(self, user_id: UUID) -> list[OrgDmRoom]:
        return list(OrgDmRoom.objects(user_id=user_id).all())

    def find_dm_pair(
        self, org_id: UUID, user_lo: UUID, user_hi: UUID
    ) -> OrgDmPair | None:
        return OrgDmPair.objects(
            org_id=org_id, user_lo=user_lo, user_hi=user_hi
        ).first()

    def create_dm_room(
        self,
        room_id: UUID,
        org_id: UUID,
        user_lo: UUID,
        user_hi: UUID,
        now: datetime,
    ) -> OrgDmPair:
        cql_run(
            f"INSERT INTO {self._keyspace}.org_dm_pairs"
            " (org_id, user_lo, user_hi, room_id, created_at)"
            " VALUES (%s, %s, %s, %s, %s) IF NOT EXISTS",
            [org_id, user_lo, user_hi, room_id, now],
        )
        # LWT loser re-reads the winner's room id; both inbox links are
        # plain upserts so a lost claim still lands them exactly once.
        # A missing row here means the claim never persisted, so fail
        # rather than blindly overwriting a possible winner's room_id.
        pair = self.find_dm_pair(org_id, user_lo, user_hi)
        if pair is None:
            raise RuntimeError("dm pair claim did not persist")
        for user, peer in ((user_lo, user_hi), (user_hi, user_lo)):
            OrgDmRoom.objects(user_id=user, room_id=pair.room_id).update(
                org_id=org_id, peer_id=peer, created_at=pair.created_at
            )
        return pair
