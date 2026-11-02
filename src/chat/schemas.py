"""Request and response bodies of the chat API."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, StringConstraints

from src.chat.rules import CHANNEL_NAME_MAX, CHANNEL_TOPIC_MAX, EMOJI_MAX, MESSAGE_LIMIT
from src.organizations.schemas import StrictRequest
from src.validation import Uuid7, multi_line, single_line

ChannelName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=CHANNEL_NAME_MAX),
    AfterValidator(single_line),
]
ChannelTopic = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=CHANNEL_TOPIC_MAX
    ),
    AfterValidator(single_line),
]
MessageBody = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MESSAGE_LIMIT),
    AfterValidator(multi_line),
]
Emoji = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=EMOJI_MAX),
    AfterValidator(single_line),
]


class ChannelCreate(StrictRequest):
    name: ChannelName
    topic: ChannelTopic | None = None
    visibility: Literal["open", "restricted"] = "open"
    member_ids: list[Uuid7] = Field(default_factory=list, max_length=100)


class MembersAdd(StrictRequest):
    user_ids: list[Uuid7] = Field(min_length=1, max_length=100)


class DmOpen(StrictRequest):
    user_id: Uuid7


class MessageSend(StrictRequest):
    body: MessageBody
    reply_to_id: Uuid7 | None = None


class MessageEdit(StrictRequest):
    body: MessageBody


class ReactionAdd(StrictRequest):
    emoji: Emoji


class ReadMark(StrictRequest):
    message_id: Uuid7


class ChannelResponse(BaseModel):
    id: uuid.UUID
    name: str
    topic: str | None
    visibility: str
    archived: bool
    created_at: datetime


class ChannelList(BaseModel):
    items: list[ChannelResponse]


class DmResponse(BaseModel):
    room_id: uuid.UUID
    peer_id: uuid.UUID
    peer_name: str


class DmList(BaseModel):
    items: list[DmResponse]


class ReactionCount(BaseModel):
    emoji: str
    count: int
    mine: bool


class ReplyPreview(BaseModel):
    id: uuid.UUID
    author_name: str
    body: str


class MessageResponse(BaseModel):
    id: uuid.UUID
    room_id: uuid.UUID
    author_id: uuid.UUID
    author_name: str
    body: str
    reply_to: ReplyPreview | None
    reactions: list[ReactionCount]
    pinned: bool
    edited_at: datetime | None
    created_at: datetime


class MessagePage(BaseModel):
    items: list[MessageResponse]
    next_before: uuid.UUID | None


class UnreadItem(BaseModel):
    room_id: uuid.UUID
    count: int


class UnreadList(BaseModel):
    items: list[UnreadItem]


class TicketResponse(BaseModel):
    ticket: str
    expires_at: datetime


class MessageList(BaseModel):
    items: list[MessageResponse]
