"""Response bodies of the inbox: every conversation of the viewer across organizations."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class InboxOrg(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    logo_url: str | None


class LastMessage(BaseModel):
    id: uuid.UUID
    author_id: uuid.UUID
    author_name: str
    # The first characters of the text. Empty when the message is only files.
    preview: str
    # 'image', 'video', or 'mixed' when the message has files; null otherwise.
    attachment_kind: str | None
    attachment_count: int
    created_at: datetime


class InboxRoom(BaseModel):
    room_id: uuid.UUID
    kind: Literal["org", "channel", "dm"]
    name: str
    topic: str | None
    restricted: bool
    org: InboxOrg
    # The organization logo for its rooms, the other person's avatar for a DM.
    avatar_url: str | None
    peer_id: uuid.UUID | None
    # Managers moderate org rooms and channels. The frontend mirrors the rules with it.
    can_manage: bool
    unread: int
    last_message: LastMessage | None


class InboxList(BaseModel):
    items: list[InboxRoom]


class Contact(BaseModel):
    user_id: uuid.UUID
    full_name: str
    avatar_url: str | None
    org: InboxOrg
    # Set when the two already have a direct message in this organization.
    room_id: uuid.UUID | None


class ContactList(BaseModel):
    items: list[Contact]
