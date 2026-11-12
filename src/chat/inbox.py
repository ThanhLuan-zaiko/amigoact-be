"""The viewer's inbox and contacts: every room they can enter in every organization.

The inbox is what the messenger page lists. Each room carries its last message and
the viewer's unread count, read with a fixed number of queries for the whole list.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from src.chat.channels import visible_channels
from src.chat.crypto import open_text
from src.chat.dms import list_dms
from src.chat.inbox_schemas import Contact, InboxOrg, InboxRoom, LastMessage
from src.chat.rules import (
    CONTACT_LIMIT,
    INBOX_PREVIEW,
    RESTRICTED,
    ROOM_CHANNEL,
    ROOM_DM,
    ROOM_ORG,
)
from src.models.auth import User
from src.models.chat import OrgDmPair, OrgRoomMedia, OrgRoomMessage, OrgRoomRead
from src.models.organizations import Organization, OrganizationMember
from src.organizations.access import ACTIVE, get_access
from src.organizations.service import live_organization

MIXED = "mixed"


def media_url(asset_id: uuid.UUID | None) -> str | None:
    return f"/media/{asset_id}/file" if asset_id is not None else None


def member_orgs(db: Session, user_id: uuid.UUID) -> list[Organization]:
    """Live organizations where the viewer is an active member, by name."""
    query = (
        select(Organization)
        .join(OrganizationMember, OrganizationMember.org_id == Organization.id)
        .where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.status == ACTIVE,
            *live_organization(),
        )
        .order_by(Organization.name)
    )
    return list(db.scalars(query))


def org_summary(org: Organization) -> InboxOrg:
    return InboxOrg(
        id=org.id, slug=org.slug, name=org.name, logo_url=media_url(org.logo_media_id)
    )


@dataclass
class _Room:
    room_id: uuid.UUID
    kind: str
    name: str
    topic: str | None
    restricted: bool
    org: InboxOrg
    avatar_url: str | None
    peer_id: uuid.UUID | None
    can_manage: bool


def _rooms_of(db: Session, org: Organization, user_id: uuid.UUID) -> list[_Room]:
    summary = org_summary(org)
    manage = get_access(db, org, user_id).can_manage
    rooms = [
        _Room(
            org.id,
            ROOM_ORG,
            org.name,
            None,
            False,
            summary,
            summary.logo_url,
            None,
            manage,
        )
    ]
    for channel in visible_channels(db, org, user_id):
        rooms.append(
            _Room(
                channel.channel_id,
                ROOM_CHANNEL,
                channel.name,
                channel.topic,
                channel.visibility == RESTRICTED,
                summary,
                summary.logo_url,
                None,
                manage,
            )
        )
    dms = list_dms(db, org, user_id)
    avatars = _avatars(db, {dm.peer_id for dm in dms})
    for dm in dms:
        rooms.append(
            _Room(
                dm.room_id,
                ROOM_DM,
                dm.peer_name,
                None,
                False,
                summary,
                media_url(avatars.get(dm.peer_id)),
                dm.peer_id,
                False,
            )
        )
    return rooms


def _avatars(
    db: Session, user_ids: set[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID | None]:
    if not user_ids:
        return {}
    rows = db.execute(
        select(User.id, User.avatar_media_id).where(
            User.id.in_(user_ids), User.avatar_media_id.is_not(None)
        )
    ).all()
    return {user_id: asset_id for user_id, asset_id in rows}


def _last_messages(
    db: Session, room_ids: list[uuid.UUID]
) -> dict[uuid.UUID, OrgRoomMessage]:
    """The newest message of each room, with DISTINCT ON over the room index."""
    query = (
        select(OrgRoomMessage)
        .where(OrgRoomMessage.room_id.in_(room_ids))
        .ext(distinct_on(OrgRoomMessage.room_id))
        .order_by(OrgRoomMessage.room_id, OrgRoomMessage.message_id.desc())
    )
    return {row.room_id: row for row in db.scalars(query)}


def unread_by_room(
    db: Session, room_ids: list[uuid.UUID], user_id: uuid.UUID
) -> dict[uuid.UUID, int]:
    """Messages by others after the viewer's read position, for many rooms at once."""
    query = (
        select(OrgRoomMessage.room_id, func.count())
        .select_from(OrgRoomMessage)
        .outerjoin(
            OrgRoomRead,
            and_(
                OrgRoomRead.room_id == OrgRoomMessage.room_id,
                OrgRoomRead.user_id == user_id,
            ),
        )
        .where(
            OrgRoomMessage.room_id.in_(room_ids),
            OrgRoomMessage.author_id != user_id,
            or_(
                OrgRoomRead.last_read_message_id.is_(None),
                OrgRoomMessage.message_id > OrgRoomRead.last_read_message_id,
            ),
        )
        .group_by(OrgRoomMessage.room_id)
    )
    return {room_id: int(count) for room_id, count in db.execute(query)}


def attachment_kind(kinds: list[str]) -> str | None:
    """One word for the files of a message: their kind, or 'mixed' for both."""
    unique = set(kinds)
    if not unique:
        return None
    return unique.pop() if len(unique) == 1 else MIXED


def preview_text(text: str) -> str:
    """One line, short enough for a row in the list."""
    return " ".join(text.split())[:INBOX_PREVIEW]


def _last_message_bodies(
    db: Session, rows: list[OrgRoomMessage]
) -> dict[uuid.UUID, LastMessage]:
    if not rows:
        return {}
    ids = [row.message_id for row in rows]
    kinds: dict[uuid.UUID, list[str]] = defaultdict(list)
    for message_id, kind in db.execute(
        select(OrgRoomMedia.message_id, OrgRoomMedia.kind).where(
            OrgRoomMedia.message_id.in_(ids), OrgRoomMedia.media_id.is_not(None)
        )
    ):
        kinds[message_id].append(kind)
    names = dict(
        db.execute(
            select(User.id, User.full_name).where(
                User.id.in_({row.author_id for row in rows})
            )
        ).all()
    )
    return {
        row.room_id: LastMessage(
            id=row.message_id,
            author_id=row.author_id,
            author_name=names.get(row.author_id, ""),
            preview=preview_text(open_text(row.body, row.message_id)),
            attachment_kind=attachment_kind(kinds[row.message_id]),
            attachment_count=len(kinds[row.message_id]),
            created_at=row.created_at,
        )
        for row in rows
    }


def inbox(db: Session, user_id: uuid.UUID) -> list[InboxRoom]:
    """Rooms with messages first, newest activity on top, then quiet rooms by name."""
    drafts = [
        room for org in member_orgs(db, user_id) for room in _rooms_of(db, org, user_id)
    ]
    if not drafts:
        return []
    room_ids = [room.room_id for room in drafts]
    last = _last_message_bodies(db, list(_last_messages(db, room_ids).values()))
    unread = unread_by_room(db, room_ids, user_id)
    items = [
        InboxRoom(
            room_id=room.room_id,
            kind=room.kind,  # type: ignore[arg-type]
            name=room.name,
            topic=room.topic,
            restricted=room.restricted,
            org=room.org,
            avatar_url=room.avatar_url,
            peer_id=room.peer_id,
            can_manage=room.can_manage,
            unread=unread.get(room.room_id, 0),
            last_message=last.get(room.room_id),
        )
        for room in drafts
    ]
    return sort_inbox(items)


def sort_inbox(items: list[InboxRoom]) -> list[InboxRoom]:
    active = [item for item in items if item.last_message is not None]
    quiet = [item for item in items if item.last_message is None]
    active.sort(
        key=lambda item: (
            item.last_message.id if item.last_message else uuid.UUID(int=0)
        ),
        reverse=True,
    )
    quiet.sort(key=lambda item: item.name.casefold())
    return active + quiet


def contacts(db: Session, user_id: uuid.UUID) -> list[Contact]:
    """Active members the viewer shares an organization with, once per organization."""
    orgs = {org.id: org_summary(org) for org in member_orgs(db, user_id)}
    if not orgs:
        return []
    rows = db.execute(
        select(OrganizationMember.org_id, User.id, User.full_name, User.avatar_media_id)
        .join(User, User.id == OrganizationMember.user_id)
        .where(
            OrganizationMember.org_id.in_(orgs),
            OrganizationMember.status == ACTIVE,
            OrganizationMember.user_id != user_id,
        )
        .order_by(User.full_name, OrganizationMember.org_id)
        .limit(CONTACT_LIMIT)
    ).all()
    rooms = _dm_rooms(db, list(orgs), user_id)
    return [
        Contact(
            user_id=peer_id,
            full_name=name,
            avatar_url=media_url(avatar),
            org=orgs[org_id],
            room_id=rooms.get((org_id, peer_id)),
        )
        for org_id, peer_id, name, avatar in rows
    ]


def _dm_rooms(
    db: Session, org_ids: list[uuid.UUID], user_id: uuid.UUID
) -> dict[tuple[uuid.UUID, uuid.UUID], uuid.UUID]:
    pairs = db.scalars(
        select(OrgDmPair).where(
            OrgDmPair.org_id.in_(org_ids),
            or_(OrgDmPair.user_lo == user_id, OrgDmPair.user_hi == user_id),
        )
    )
    return {
        (
            pair.org_id,
            pair.user_hi if pair.user_lo == user_id else pair.user_lo,
        ): pair.room_id
        for pair in pairs
    }
