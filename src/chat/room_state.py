"""Pinned messages, read positions, and unread counts."""

import uuid
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.auth.errors import api_error
from src.chat.channels import visible_channels
from src.chat.dms import list_dms
from src.chat.rooms import Room, can_moderate
from src.chat.schemas import UnreadItem
from src.models.chat import OrgRoomMessage, OrgRoomPin, OrgRoomRead
from src.models.organizations import Organization


def pin_message(
    db: Session, room: Room, message: OrgRoomMessage, user_id: uuid.UUID
) -> None:
    if not can_moderate(room, user_id):
        raise api_error(status.HTTP_403_FORBIDDEN, "message_forbidden")
    db.execute(
        insert(OrgRoomPin)
        .values(room_id=room.room_id, message_id=message.message_id, pinned_by=user_id)
        .on_conflict_do_nothing()
    )
    db.commit()


def unpin_message(
    db: Session, room: Room, message: OrgRoomMessage, user_id: uuid.UUID
) -> None:
    if not can_moderate(room, user_id):
        raise api_error(status.HTTP_403_FORBIDDEN, "message_forbidden")
    pin = db.get(OrgRoomPin, (room.room_id, message.message_id))
    if pin is not None:
        db.delete(pin)
        db.commit()


def list_pins(db: Session, room: Room) -> list[OrgRoomMessage]:
    rows = db.scalars(
        select(OrgRoomMessage)
        .join(OrgRoomPin, OrgRoomPin.message_id == OrgRoomMessage.message_id)
        .where(OrgRoomPin.room_id == room.room_id)
        .order_by(OrgRoomPin.pinned_at.desc(), OrgRoomMessage.message_id.desc())
    )
    return list(rows)


def mark_read(
    db: Session, room: Room, message: OrgRoomMessage, user_id: uuid.UUID
) -> None:
    """The read position only moves forward, so an old message cannot undo a newer one."""
    read = db.get(OrgRoomRead, (room.room_id, user_id))
    now = datetime.now(UTC)
    if read is None:
        db.add(
            OrgRoomRead(
                room_id=room.room_id,
                user_id=user_id,
                last_read_message_id=message.message_id,
                last_read_at=now,
            )
        )
    elif (
        read.last_read_message_id is None
        or read.last_read_message_id < message.message_id
    ):
        read.last_read_message_id = message.message_id
        read.last_read_at = now
    db.commit()


def _unread(db: Session, room_id: uuid.UUID, user_id: uuid.UUID) -> int:
    """Messages after the read position that someone else wrote."""
    read = db.get(OrgRoomRead, (room_id, user_id))
    query = (
        select(func.count())
        .select_from(OrgRoomMessage)
        .where(
            OrgRoomMessage.room_id == room_id,
            OrgRoomMessage.author_id != user_id,
        )
    )
    if read is not None and read.last_read_message_id is not None:
        query = query.where(OrgRoomMessage.message_id > read.last_read_message_id)
    return int(db.scalar(query) or 0)


def unread_counts(
    db: Session, org: Organization, user_id: uuid.UUID
) -> list[UnreadItem]:
    """The general room, every channel the viewer can enter, and their direct messages."""
    room_ids = [org.id]
    room_ids += [channel.channel_id for channel in visible_channels(db, org, user_id)]
    room_ids += [dm.room_id for dm in list_dms(db, org, user_id)]
    return [
        UnreadItem(room_id=room_id, count=_unread(db, room_id, user_id))
        for room_id in room_ids
    ]
