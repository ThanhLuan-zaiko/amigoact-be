"""Turning message rows into response bodies with a fixed number of queries per list."""

import uuid
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.chat.crypto import open_text
from src.chat.schemas import MessageResponse, ReactionCount, ReplyPreview
from src.models.auth import User
from src.models.chat import OrgRoomMessage, OrgRoomPin, OrgRoomReaction


def message_responses(
    db: Session,
    messages: list[OrgRoomMessage],
    viewer_id: uuid.UUID | None,
) -> list[MessageResponse]:
    """The viewer only changes the "mine" flags and nothing else, so events can omit it."""
    if not messages:
        return []
    ids = [message.message_id for message in messages]
    authors = dict(
        db.execute(
            select(User.id, User.full_name).where(
                User.id.in_({message.author_id for message in messages})
            )
        ).all()
    )
    reactions: dict[uuid.UUID, list[ReactionCount]] = defaultdict(list)
    mine: set[tuple[uuid.UUID, str]] = set()
    counts = db.execute(
        select(OrgRoomReaction.message_id, OrgRoomReaction.emoji, func.count())
        .where(OrgRoomReaction.message_id.in_(ids))
        .group_by(OrgRoomReaction.message_id, OrgRoomReaction.emoji)
        .order_by(OrgRoomReaction.emoji)
    ).all()
    if viewer_id is not None:
        mine = set(
            db.execute(
                select(OrgRoomReaction.message_id, OrgRoomReaction.emoji).where(
                    OrgRoomReaction.message_id.in_(ids),
                    OrgRoomReaction.user_id == viewer_id,
                )
            ).all()
        )
    for message_id, emoji, count in counts:
        reactions[message_id].append(
            ReactionCount(emoji=emoji, count=count, mine=(message_id, emoji) in mine)
        )
    pinned = set(
        db.scalars(
            select(OrgRoomPin.message_id).where(OrgRoomPin.message_id.in_(ids))
        ).all()
    )
    return [
        MessageResponse(
            id=message.message_id,
            room_id=message.room_id,
            author_id=message.author_id,
            author_name=authors.get(message.author_id, ""),
            body=open_text(message.body, message.message_id),
            reply_to=_reply(message),
            reactions=reactions[message.message_id],
            pinned=message.message_id in pinned,
            edited_at=message.edited_at,
            created_at=message.created_at,
        )
        for message in messages
    ]


def _reply(message: OrgRoomMessage) -> ReplyPreview | None:
    if message.reply_to_id is None:
        return None
    body = ""
    if message.reply_to_body is not None:
        body = open_text(message.reply_to_body, message.reply_to_id)
    return ReplyPreview(
        id=message.reply_to_id,
        author_name=message.reply_to_author or "",
        body=body,
    )
