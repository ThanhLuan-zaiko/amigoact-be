"""Chat tables: channels, direct messages, messages, and their reads, pins, and reactions."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models import auth, organizations  # noqa: F401  registers the foreign key targets
from src.models.base import Base


class OrgChatChannel(Base):
    __tablename__ = "org_chat_channels"

    channel_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str]
    name_folded: Mapped[str]
    topic: Mapped[str | None]
    # 'open' for every member, 'restricted' for the people in org_chat_channel_members.
    visibility: Mapped[str] = mapped_column(server_default="open")
    # Top-level channels point at their organization, as the general room does.
    parent_room_id: Mapped[uuid.UUID | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    archived_at: Mapped[datetime | None]
    archived_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class OrgChannelMember(Base):
    __tablename__ = "org_chat_channel_members"

    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("org_chat_channels.channel_id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    added_at: Mapped[datetime] = mapped_column(server_default=func.now())


class OrgDmPair(Base):
    """One row per pair. user_lo < user_hi, so a pair cannot be stored twice."""

    __tablename__ = "org_dm_pairs"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    user_lo: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    user_hi: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    room_id: Mapped[uuid.UUID] = mapped_column(unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class OrgRoomMessage(Base):
    __tablename__ = "org_room_messages"

    message_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    room_id: Mapped[uuid.UUID]
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str]
    # The reply keeps a copy of the author and text, so it still reads after the original is deleted.
    reply_to_id: Mapped[uuid.UUID | None]
    reply_to_author: Mapped[str | None]
    reply_to_body: Mapped[str | None]
    edited_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class OrgRoomRead(Base):
    __tablename__ = "org_room_reads"

    room_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    last_read_message_id: Mapped[uuid.UUID | None]
    last_read_at: Mapped[datetime | None]


class OrgRoomPin(Base):
    __tablename__ = "org_room_pins"

    room_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("org_room_messages.message_id", ondelete="CASCADE"), primary_key=True
    )
    pinned_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    pinned_at: Mapped[datetime] = mapped_column(server_default=func.now())


class OrgRoomReaction(Base):
    __tablename__ = "org_room_reactions"

    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("org_room_messages.message_id", ondelete="CASCADE"), primary_key=True
    )
    emoji: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    room_id: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class WsTicket(Base):
    """A one-time handshake ticket. Only its SHA-256 hash is stored."""

    __tablename__ = "ws_tickets"

    ticket_hash: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    expires_at: Mapped[datetime] = mapped_column(server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
