"""Channels of an organization: creating, listing, archiving, and who may enter a restricted one."""

import uuid
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.auth.errors import api_error
from src.chat.rooms import Room
from src.chat.rules import OPEN, RESTRICTED
from src.chat.schemas import ChannelCreate
from src.models.chat import OrgChannelMember, OrgChatChannel
from src.models.organizations import Organization
from src.organizations.access import ACTIVE, get_access
from src.validation import validation_failure


def visible_channels(
    db: Session, org: Organization, viewer_id: uuid.UUID
) -> list[OrgChatChannel]:
    """Open channels, plus restricted ones the viewer is in. Managers see every channel."""
    access = get_access(db, org, viewer_id)
    query = select(OrgChatChannel).where(
        OrgChatChannel.org_id == org.id,
        OrgChatChannel.archived_at.is_(None),
    )
    if not access.can_manage:
        entered = select(OrgChannelMember.channel_id).where(
            OrgChannelMember.user_id == viewer_id
        )
        query = query.where(
            or_(
                OrgChatChannel.visibility == OPEN,
                OrgChatChannel.channel_id.in_(entered),
            )
        )
    return list(db.scalars(query.order_by(OrgChatChannel.name_folded)))


def _active_member_ids(
    db: Session, org: Organization, user_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """Every id must belong to an active member, or the whole request is refused."""
    unique = list(dict.fromkeys(user_ids))
    for user_id in unique:
        if get_access(db, org, user_id).status != ACTIVE:
            raise validation_failure({"user_ids": "not_a_member"})
    return unique


def create_channel(
    db: Session, org: Organization, user_id: uuid.UUID, payload: ChannelCreate
) -> OrgChatChannel:
    if not get_access(db, org, user_id).can_manage:
        raise api_error(status.HTTP_403_FORBIDDEN, "organization_forbidden")
    if payload.member_ids and payload.visibility != RESTRICTED:
        raise validation_failure({"member_ids": "needs_restricted_channel"})
    member_ids = _active_member_ids(db, org, payload.member_ids)
    channel = OrgChatChannel(
        channel_id=uuid.uuid7(),
        org_id=org.id,
        name=payload.name,
        name_folded=payload.name.casefold(),
        topic=payload.topic,
        visibility=payload.visibility,
        parent_room_id=org.id,
        created_by=user_id,
    )
    db.add(channel)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise api_error(status.HTTP_409_CONFLICT, "channel_name_taken") from exc
    for member_id in member_ids:
        db.add(
            OrgChannelMember(
                channel_id=channel.channel_id, user_id=member_id, added_by=user_id
            )
        )
    db.commit()
    return channel


def archive_channel(db: Session, room: Room, user_id: uuid.UUID) -> None:
    """Archived channels stay readable, so their history is kept, but nobody writes to them."""
    if room.channel is None or not room.is_manager:
        raise api_error(status.HTTP_403_FORBIDDEN, "organization_forbidden")
    if room.archived:
        raise api_error(status.HTTP_409_CONFLICT, "channel_archived")
    room.channel.archived_at = datetime.now(UTC)
    room.channel.archived_by = user_id
    db.commit()


def add_members(
    db: Session,
    room: Room,
    org: Organization,
    user_ids: list[uuid.UUID],
    actor_id: uuid.UUID,
) -> None:
    if room.channel is None or not room.is_manager:
        raise api_error(status.HTTP_403_FORBIDDEN, "organization_forbidden")
    if room.channel.visibility != RESTRICTED:
        raise api_error(status.HTTP_409_CONFLICT, "channel_not_restricted")
    for user_id in _active_member_ids(db, org, user_ids):
        db.execute(
            insert(OrgChannelMember)
            .values(channel_id=room.room_id, user_id=user_id, added_by=actor_id)
            .on_conflict_do_nothing()
        )
    db.commit()


def remove_member(db: Session, room: Room, user_id: uuid.UUID) -> None:
    if room.channel is None or not room.is_manager:
        raise api_error(status.HTTP_403_FORBIDDEN, "organization_forbidden")
    member = db.get(OrgChannelMember, (room.room_id, user_id))
    if member is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "channel_member_not_found")
    db.delete(member)
    db.commit()
