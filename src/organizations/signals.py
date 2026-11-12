"""Live events of an organization and the topics a person loses with their access.

Call these before the commit. Events are signals only: pages fetch what changed
through the API, which checks access again.
"""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.chat.rules import RESTRICTED
from src.models.chat import OrgChannelMember, OrgChatChannel, OrgDmPair
from src.realtime import bus
from src.realtime.names import managers_topic, org_topic, room_topic, user_topic


def members_changed(db: Session, org_id: uuid.UUID) -> None:
    """Someone joined, left, was removed, or changed role."""
    bus.emit(db, org_topic(org_id), {"type": "members.changed", "org_id": str(org_id)})


def applications_changed(db: Session, org_id: uuid.UUID) -> None:
    """An application arrived, was withdrawn, or was decided."""
    bus.emit(
        db,
        managers_topic(org_id),
        {"type": "applications.changed", "org_id": str(org_id)},
    )


def membership_changed(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """The person's own standing changed, so their view of the organization reloads."""
    bus.emit(
        db,
        user_topic(user_id),
        {"type": "membership.changed", "org_id": str(org_id)},
    )


def member_topics(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> list[str]:
    """Every topic of the organization this person could be listening to."""
    channels = db.scalars(
        select(OrgChatChannel.channel_id).where(OrgChatChannel.org_id == org_id)
    )
    dms = db.scalars(
        select(OrgDmPair.room_id).where(
            OrgDmPair.org_id == org_id,
            or_(OrgDmPair.user_lo == user_id, OrgDmPair.user_hi == user_id),
        )
    )
    rooms = [org_id, *channels, *dms]
    return [
        org_topic(org_id),
        managers_topic(org_id),
        *(room_topic(room) for room in rooms),
    ]


def manager_topics(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> list[str]:
    """What only a manager hears: review work and restricted channels they are not in."""
    joined = select(OrgChannelMember.channel_id).where(
        OrgChannelMember.user_id == user_id
    )
    restricted = db.scalars(
        select(OrgChatChannel.channel_id).where(
            OrgChatChannel.org_id == org_id,
            OrgChatChannel.visibility == RESTRICTED,
            OrgChatChannel.channel_id.not_in(joined),
        )
    )
    return [managers_topic(org_id), *(room_topic(room) for room in restricted)]


def lose_membership(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """A socket checks access only when it subscribes, so lost topics are cut here."""
    bus.revoke(db, user_id, member_topics(db, org_id, user_id))


def lose_manager_role(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
    bus.revoke(db, user_id, manager_topics(db, org_id, user_id))
