"""Routes for messages in a room: reading, sending, editing, reacting, pinning, and marking read."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from src.auth.deps import CurrentPrincipal, Db
from src.auth.errors import api_error
from src.chat import messages, room_state
from src.chat.hub import publish
from src.chat.rooms import Room, load_room
from src.chat.rules import EMOJI_MAX
from src.chat.schemas import (
    MessageEdit,
    MessageList,
    MessagePage,
    MessageResponse,
    MessageSend,
    ReactionAdd,
    ReadMark,
)
from src.chat.views import message_responses
from src.models.chat import OrgRoomMessage
from src.validation import Uuid7

router = APIRouter(tags=["chat"])

Limit = Annotated[int, Query(ge=1, le=100)]
Before = Annotated[Uuid7 | None, Query()]
Emoji = Annotated[str, Path(min_length=1, max_length=EMOJI_MAX)]


def _event(kind: str, response: MessageResponse) -> dict[str, object]:
    return {
        "type": kind,
        "room_id": str(response.room_id),
        "message": response.model_dump(mode="json"),
    }


def _publish_message(db: Db, kind: str, message: OrgRoomMessage) -> None:
    """Sockets get the message without viewer-specific flags, so one copy serves them all."""
    response = message_responses(db, [message], None)[0]
    publish(message.room_id, _event(kind, response))


def _load_with_room(
    db: Db, message_id: uuid.UUID, viewer: uuid.UUID
) -> tuple[OrgRoomMessage, Room]:
    row = db.get(OrgRoomMessage, message_id)
    if row is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "message_not_found")
    return row, load_room(db, row.room_id, viewer)


@router.get("/rooms/{room_id}/messages")
def list_messages(
    room_id: Uuid7,
    principal: CurrentPrincipal,
    db: Db,
    before: Before = None,
    limit: Limit = 50,
) -> MessagePage:
    room = load_room(db, room_id, principal.user.id)
    rows = messages.list_messages(db, room, before=before, limit=limit)
    next_before = rows[limit - 1].message_id if len(rows) > limit else None
    items = message_responses(db, rows[:limit], principal.user.id)
    return MessagePage(items=items, next_before=next_before)


@router.post("/rooms/{room_id}/messages", status_code=status.HTTP_201_CREATED)
def send_message(
    room_id: Uuid7, payload: MessageSend, principal: CurrentPrincipal, db: Db
) -> MessageResponse:
    room = load_room(db, room_id, principal.user.id)
    message = messages.send_message(db, room, principal.user.id, payload)
    response = message_responses(db, [message], principal.user.id)[0]
    publish(room.room_id, _event("message.created", response))
    return response


@router.patch("/messages/{message_id}")
def edit_message(
    message_id: Uuid7, payload: MessageEdit, principal: CurrentPrincipal, db: Db
) -> MessageResponse:
    message, room = _load_with_room(db, message_id, principal.user.id)
    message = messages.edit_message(db, room, message, principal.user.id, payload.body)
    _publish_message(db, "message.updated", message)
    return message_responses(db, [message], principal.user.id)[0]


@router.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_message(message_id: Uuid7, principal: CurrentPrincipal, db: Db) -> None:
    message, room = _load_with_room(db, message_id, principal.user.id)
    room_key = message.room_id
    deleted_id = message.message_id
    messages.delete_message(db, room, message, principal.user.id)
    publish(
        room_key,
        {
            "type": "message.deleted",
            "room_id": str(room_key),
            "message_id": str(deleted_id),
        },
    )


@router.post("/messages/{message_id}/reactions", status_code=status.HTTP_204_NO_CONTENT)
def add_reaction(
    message_id: Uuid7, payload: ReactionAdd, principal: CurrentPrincipal, db: Db
) -> None:
    message, room = _load_with_room(db, message_id, principal.user.id)
    messages.add_reaction(db, room, message, principal.user.id, payload.emoji)
    _publish_message(db, "message.updated", message)


@router.delete(
    "/messages/{message_id}/reactions/{emoji}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_reaction(
    message_id: Uuid7, emoji: Emoji, principal: CurrentPrincipal, db: Db
) -> None:
    message, _room = _load_with_room(db, message_id, principal.user.id)
    messages.remove_reaction(db, message, principal.user.id, emoji)
    _publish_message(db, "message.updated", message)


@router.get("/rooms/{room_id}/pins")
def list_pins(room_id: Uuid7, principal: CurrentPrincipal, db: Db) -> MessageList:
    room = load_room(db, room_id, principal.user.id)
    rows = room_state.list_pins(db, room)
    return MessageList(items=message_responses(db, rows, principal.user.id))


@router.post(
    "/rooms/{room_id}/pins/{message_id}", status_code=status.HTTP_204_NO_CONTENT
)
def pin_message(
    room_id: Uuid7, message_id: Uuid7, principal: CurrentPrincipal, db: Db
) -> None:
    room = load_room(db, room_id, principal.user.id)
    message = messages.load_message(db, room, message_id)
    room_state.pin_message(db, room, message, principal.user.id)
    _publish_message(db, "message.updated", message)


@router.delete(
    "/rooms/{room_id}/pins/{message_id}", status_code=status.HTTP_204_NO_CONTENT
)
def unpin_message(
    room_id: Uuid7, message_id: Uuid7, principal: CurrentPrincipal, db: Db
) -> None:
    room = load_room(db, room_id, principal.user.id)
    message = messages.load_message(db, room, message_id)
    room_state.unpin_message(db, room, message, principal.user.id)
    _publish_message(db, "message.updated", message)


@router.post("/rooms/{room_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(
    room_id: Uuid7, payload: ReadMark, principal: CurrentPrincipal, db: Db
) -> None:
    room = load_room(db, room_id, principal.user.id)
    message = messages.load_message(db, room, payload.message_id)
    room_state.mark_read(db, room, message, principal.user.id)
