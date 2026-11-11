"""Sending, editing, deleting, and reacting to messages in a room."""

import uuid
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.auth.errors import api_error
from src.auth.rate_limit import enforce_rate_limit
from src.chat.crypto import open_text, seal
from src.chat.rooms import Room, can_delete, require_writable
from src.chat.rules import REPLY_PREVIEW, SEND_LIMIT, SEND_WINDOW
from src.chat.schemas import MessageSend
from src.models.auth import User
from src.models.chat import OrgRoomMessage, OrgRoomReaction
from src.validation import validation_failure

PAGE_LIMIT_MAX = 100


def load_message(db: Session, room: Room, message_id: uuid.UUID) -> OrgRoomMessage:
    message = db.get(OrgRoomMessage, message_id)
    if message is None or message.room_id != room.room_id:
        raise api_error(status.HTTP_404_NOT_FOUND, "message_not_found")
    return message


def _author_name(db: Session, user_id: uuid.UUID) -> str:
    return db.scalar(select(User.full_name).where(User.id == user_id)) or ""


def send_message(
    db: Session, room: Room, user_id: uuid.UUID, payload: MessageSend
) -> OrgRoomMessage:
    require_writable(room)
    enforce_rate_limit(db, f"chat-send:{user_id}", SEND_LIMIT, SEND_WINDOW)
    message_id = uuid.uuid7()
    reply_author = None
    reply_body = None
    if payload.reply_to_id is not None:
        parent = db.get(OrgRoomMessage, payload.reply_to_id)
        if parent is None or parent.room_id != room.room_id:
            raise validation_failure({"reply_to_id": "not_in_room"})
        reply_author = _author_name(db, parent.author_id)
        # The copy is sealed against the parent, so it opens only as that parent text.
        parent_text = open_text(parent.body, parent.message_id)
        reply_body = seal(parent_text[:REPLY_PREVIEW], parent.message_id)
    message = OrgRoomMessage(
        message_id=message_id,
        room_id=room.room_id,
        author_id=user_id,
        body=seal(payload.body, message_id),
        reply_to_id=payload.reply_to_id,
        reply_to_author=reply_author,
        reply_to_body=reply_body,
    )
    db.add(message)
    db.commit()
    return message


def edit_message(
    db: Session, room: Room, message: OrgRoomMessage, user_id: uuid.UUID, body: str
) -> OrgRoomMessage:
    """Only the author edits. Replies keep the text they quoted when they were sent."""
    if message.author_id != user_id:
        raise api_error(status.HTTP_403_FORBIDDEN, "message_forbidden")
    require_writable(room)
    message.body = seal(body, message.message_id)
    message.edited_at = datetime.now(UTC)
    db.commit()
    return message


def delete_message(
    db: Session, room: Room, message: OrgRoomMessage, user_id: uuid.UUID
) -> None:
    """The author, or a manager outside DMs, deletes. Pins and reactions go with it."""
    if not can_delete(room, message.author_id, user_id):
        raise api_error(status.HTTP_403_FORBIDDEN, "message_forbidden")
    db.delete(message)
    db.commit()


def list_messages(
    db: Session,
    room: Room,
    *,
    before: uuid.UUID | None,
    limit: int,
) -> list[OrgRoomMessage]:
    """Newest first. The message ID is time ordered, so it is also the cursor."""
    query = select(OrgRoomMessage).where(OrgRoomMessage.room_id == room.room_id)
    if before is not None:
        query = query.where(OrgRoomMessage.message_id < before)
    rows = db.scalars(query.order_by(OrgRoomMessage.message_id.desc()).limit(limit + 1))
    return list(rows)


def add_reaction(
    db: Session, room: Room, message: OrgRoomMessage, user_id: uuid.UUID, emoji: str
) -> None:
    require_writable(room)
    db.execute(
        insert(OrgRoomReaction)
        .values(
            message_id=message.message_id,
            emoji=emoji,
            user_id=user_id,
            room_id=room.room_id,
        )
        .on_conflict_do_nothing()
    )
    db.commit()


def remove_reaction(
    db: Session, message: OrgRoomMessage, user_id: uuid.UUID, emoji: str
) -> None:
    if not emoji:
        raise validation_failure({"emoji": "string_too_short"})
    db.execute(
        delete(OrgRoomReaction).where(
            OrgRoomReaction.message_id == message.message_id,
            OrgRoomReaction.emoji == emoji,
            OrgRoomReaction.user_id == user_id,
        )
    )
    db.commit()
