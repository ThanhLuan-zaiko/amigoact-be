"""cqlengine persistence for org chat rooms and read pointers.

The dm pair claim uses raw CQL LWT because cqlengine cannot surface the
IF NOT EXISTS result needed to converge both callers on one room id
(same justification as the slug claims elsewhere).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from cassandra.cqlengine.connection import get_session

from chat.interfaces import ChatStore
from chat.model import (
    OrgDmPair,
    OrgDmRoom,
    OrgRoomMessage,
    OrgRoomMute,
    OrgRoomPin,
    OrgRoomReaction,
    OrgRoomRead,
)


class CqlChatStore(ChatStore):
    """Room message partitions, read pointers, and dm room rows."""

    def __init__(self, keyspace: str = "amigoact") -> None:
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

    def set_reaction(
        self,
        room_id: UUID,
        message_id: UUID,
        user_id: UUID,
        emoji: str,
        now: datetime,
    ) -> bool:
        key = dict(
            room_id=room_id,
            message_id=message_id,
            emoji=emoji,
            user_id=user_id,
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
                room_id=room_id, message_id=message_id
            ).all()
        )

    def set_pin(
        self,
        room_id: UUID,
        message_id: UUID,
        pinned_by: UUID,
        now: datetime,
    ) -> None:
        OrgRoomPin.objects(room_id=room_id).update(
            message_id=message_id, pinned_by=pinned_by, pinned_at=now
        )

    def clear_pin(self, room_id: UUID) -> None:
        OrgRoomPin.objects(room_id=room_id).delete()

    def get_pin(self, room_id: UUID) -> OrgRoomPin | None:
        return OrgRoomPin.objects(room_id=room_id).first()

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
        session = get_session()
        session.execute(
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
