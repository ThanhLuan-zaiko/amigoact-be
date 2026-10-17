"""cqlengine persistence for named org channels and their rosters.

The name claim uses raw CQL LWT because cqlengine cannot surface the
IF NOT EXISTS result (same justification as the dm pair claim). Writes
mirror to org_chat_channels (org listing) and org_chat_channels_by_id
(room resolution) like members/members_by_user do.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from cassandra.cqlengine.connection import get_session

from chat.channel_interfaces import ChannelStore
from core.ids import uuid7
from chat.model import (
    OrgChatChannel,
    OrgChatChannelById,
    OrgChatChannelMember,
    OrgChatChannelMembership,
    OrgChatChannelName,
)


def _mirror(row: OrgChatChannel) -> OrgChatChannelById:
    """Project an org-partition row into the by-id row shape."""
    return OrgChatChannelById(
        channel_id=row.channel_id,
        org_id=row.org_id,
        name=row.name,
        name_folded=row.name_folded,
        topic=row.topic,
        kind=row.kind,
        post_policy=row.post_policy,
        visibility=row.visibility,
        created_by=row.created_by,
        created_at=row.created_at,
        archived_at=row.archived_at,
        archived_by=row.archived_by,
    )


class CqlChannelStore(ChannelStore):
    """Channel metadata partitions plus restricted-channel rosters."""

    def __init__(self, keyspace: str = "amigoact") -> None:
        self._keyspace = keyspace

    def _claim_once(
        self, org_id: UUID, name_folded: str, channel_id: UUID, now: datetime
    ) -> None:
        get_session().execute(
            f"INSERT INTO {self._keyspace}.org_chat_channel_names"
            " (org_id, name_folded, channel_id, created_at)"
            " VALUES (%s, %s, %s, %s) IF NOT EXISTS",
            [org_id, name_folded, channel_id, now],
        )

    def claim_name(
        self,
        org_id: UUID,
        name_folded: str,
        channel_id: UUID,
        now: datetime,
    ) -> bool:
        self._claim_once(org_id, name_folded, channel_id, now)
        claim = OrgChatChannelName.objects(
            org_id=org_id, name_folded=name_folded
        ).first()
        if claim is None:
            raise RuntimeError("channel name claim did not persist")
        if claim.channel_id == channel_id:
            return True
        holder = self.get_channel(claim.channel_id)
        if holder is not None and holder.archived_at is None:
            return False
        # Stale claim (holder deleted mid-flight or already archived):
        # release and retry once, as documented on the port.
        self.release_name(org_id, name_folded)
        self._claim_once(org_id, name_folded, channel_id, now)
        claim = OrgChatChannelName.objects(
            org_id=org_id, name_folded=name_folded
        ).first()
        return claim is not None and claim.channel_id == channel_id

    def release_name(self, org_id: UUID, name_folded: str) -> None:
        OrgChatChannelName.objects(
            org_id=org_id, name_folded=name_folded
        ).delete()

    def create_channel(
        self,
        org_id: UUID,
        name: str,
        topic: str,
        kind: str,
        post_policy: str,
        visibility: str,
        created_by: UUID,
        now: datetime,
    ) -> OrgChatChannelById | None:
        channel_id = uuid7()
        name_folded = name.casefold()
        if not self.claim_name(org_id, name_folded, channel_id, now):
            return None
        row = OrgChatChannelById(
            channel_id=channel_id,
            org_id=org_id,
            name=name,
            name_folded=name_folded,
            topic=topic,
            kind=kind,
            post_policy=post_policy,
            visibility=visibility,
            created_by=created_by,
            created_at=now,
        )
        self._write(row)
        return row

    def _write(self, row: OrgChatChannelById) -> None:
        fields = dict(
            name=row.name,
            name_folded=row.name_folded,
            topic=row.topic,
            kind=row.kind,
            post_policy=row.post_policy,
            visibility=row.visibility,
            created_by=row.created_by,
            created_at=row.created_at,
            archived_at=row.archived_at,
            archived_by=row.archived_by,
        )
        OrgChatChannel.objects(
            org_id=row.org_id, channel_id=row.channel_id
        ).update(**fields)
        OrgChatChannelById.objects(channel_id=row.channel_id).update(
            org_id=row.org_id, **fields
        )

    def update_channel(self, channel: OrgChatChannelById) -> None:
        self._write(channel)

    def get_channel(self, channel_id: UUID) -> OrgChatChannelById | None:
        return OrgChatChannelById.objects(channel_id=channel_id).first()

    def get_channel_in_org(
        self, org_id: UUID, channel_id: UUID
    ) -> OrgChatChannelById | None:
        row = self.get_channel(channel_id)
        return row if row is not None and row.org_id == org_id else None

    def list_channels(self, org_id: UUID) -> list[OrgChatChannelById]:
        rows = OrgChatChannel.objects(org_id=org_id).all()
        return [_mirror(row) for row in rows]

    def add_channel_member(
        self,
        channel_id: UUID,
        org_id: UUID,
        user_id: UUID,
        added_by: UUID,
        now: datetime,
    ) -> None:
        OrgChatChannelMember.objects(
            channel_id=channel_id, user_id=user_id
        ).update(added_by=added_by, added_at=now)
        OrgChatChannelMembership.objects(
            user_id=user_id, channel_id=channel_id
        ).update(org_id=org_id, added_at=now)

    def remove_channel_member(
        self, channel_id: UUID, user_id: UUID
    ) -> None:
        OrgChatChannelMember.objects(
            channel_id=channel_id, user_id=user_id
        ).delete()
        OrgChatChannelMembership.objects(
            user_id=user_id, channel_id=channel_id
        ).delete()

    def get_channel_member(
        self, channel_id: UUID, user_id: UUID
    ) -> OrgChatChannelMember | None:
        return OrgChatChannelMember.objects(
            channel_id=channel_id, user_id=user_id
        ).first()

    def list_channel_members(
        self, channel_id: UUID
    ) -> list[OrgChatChannelMember]:
        return list(
            OrgChatChannelMember.objects(channel_id=channel_id).all()
        )

    def list_channel_memberships(
        self, user_id: UUID
    ) -> list[OrgChatChannelMembership]:
        return list(
            OrgChatChannelMembership.objects(user_id=user_id).all()
        )
