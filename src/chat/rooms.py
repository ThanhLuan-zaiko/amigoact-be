"""Finding a room and deciding what its members may do there."""

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.errors import api_error
from src.chat.rules import RESTRICTED, ROOM_CHANNEL, ROOM_DM, ROOM_ORG
from src.models.chat import OrgChannelMember, OrgChatChannel, OrgDmPair
from src.models.organizations import Organization
from src.organizations.access import ACTIVE, get_access
from src.organizations.service import live_organization
from src.posts.visibility import load_live_org


@dataclass(frozen=True)
class Room:
    room_id: uuid.UUID
    org_id: uuid.UUID
    kind: str
    # Set for channels only. An archived channel can be read but not written to.
    channel: OrgChatChannel | None
    # Managers of the organization moderate org rooms and channels.
    is_manager: bool
    dm_pair: OrgDmPair | None = None

    @property
    def archived(self) -> bool:
        return self.channel is not None and self.channel.archived_at is not None


def _not_found() -> HTTPException:
    return api_error(status.HTTP_404_NOT_FOUND, "room_not_found")


def load_room(db: Session, room_id: uuid.UUID, viewer_id: uuid.UUID) -> Room:
    """A room the viewer may not see looks like it does not exist."""
    org = db.scalar(
        select(Organization).where(Organization.id == room_id, *live_organization())
    )
    if org is not None:
        access = get_access(db, org, viewer_id)
        if access.status != ACTIVE:
            raise _not_found()
        return Room(room_id, org.id, ROOM_ORG, None, access.can_manage)

    channel = db.get(OrgChatChannel, room_id)
    if channel is not None:
        org = load_live_org(db, channel.org_id)
        access = get_access(db, org, viewer_id)
        if access.status != ACTIVE:
            raise _not_found()
        hidden = channel.visibility == RESTRICTED and not access.can_manage
        if hidden and not is_channel_member(db, channel.channel_id, viewer_id):
            raise _not_found()
        return Room(room_id, org.id, ROOM_CHANNEL, channel, access.can_manage)

    pair = db.scalar(select(OrgDmPair).where(OrgDmPair.room_id == room_id))
    if pair is not None and viewer_id in (pair.user_lo, pair.user_hi):
        org = load_live_org(db, pair.org_id)
        if get_access(db, org, viewer_id).status != ACTIVE:
            raise _not_found()
        return Room(room_id, org.id, ROOM_DM, None, False, dm_pair=pair)
    raise _not_found()


def is_channel_member(db: Session, channel_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return db.get(OrgChannelMember, (channel_id, user_id)) is not None


def readable_by(db: Session, room_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    try:
        load_room(db, room_id, user_id)
    except HTTPException:
        return False
    return True


def require_writable(room: Room) -> None:
    if room.archived:
        raise api_error(status.HTTP_409_CONFLICT, "channel_archived")


def can_moderate(room: Room, user_id: uuid.UUID) -> bool:
    """Who pins. Managers in org rooms and channels; in a DM, the two people in it."""
    if room.kind == ROOM_DM:
        return room.dm_pair is not None and user_id in (
            room.dm_pair.user_lo,
            room.dm_pair.user_hi,
        )
    return room.is_manager


def can_delete(room: Room, author_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """The author always deletes. Managers delete in org rooms and channels.

    A DM has no moderator: pinning is shared by the pair, but deleting is not, so one
    person cannot remove what the other wrote.
    """
    if author_id == user_id:
        return True
    return room.kind != ROOM_DM and room.is_manager
