"""Per-room moderation and read state: delete, react, pin, mute, read."""

from __future__ import annotations

from uuid import UUID

from chat.dtos import (
    ChatMessageSnapshot,
    ReadSnapshot,
    RoomReadSnapshot,
)
from chat.attachments import ChatAttachments
from chat.helpers import (
    REACTION_EMOJIS,
    avatar_url,
    bucket_of_uuid,
    decode_attachments,
    message_snapshot,
    tally_reactions,
)
from chat.channel_interfaces import ChannelStore
from chat.interfaces import (
    ActivityLookup,
    ChatEvents,
    ChatStore,
)
from chat.model import OrgRoomMessage
from chat.rooms import emit, emit_inbox, open_room, require_live_activity
from core.exceptions import (
    ChannelArchivedError,
    ForbiddenError,
    InvalidMemberStateError,
    NotFoundError,
    PinLimitReachedError,
)
from core.security import utc_aware, utcnow
from orgs.interfaces import (
    MediaRepository,
    MemberRepository,
    OrgRepository,
    UserDirectory,
)
from orgs.member_helpers import is_active_member
from rbac.interfaces import AccessControl

MAX_PINS = 20


class ChatRoomAdmin:
    """Message/room state operations split off ChatService for size.

    Same port set; every call re-proves room access through open_room
    before touching persistence, mirroring ChatService's rules.
    """

    def __init__(
        self,
        chat: ChatStore,
        orgs: OrgRepository,
        members: MemberRepository,
        users: UserDirectory,
        access: AccessControl,
        events: ChatEvents,
        activities: ActivityLookup | None = None,
        cipher=None,  # noqa: ANN001
        media: MediaRepository | None = None,
        channels: ChannelStore | None = None,
        attachments: ChatAttachments | None = None,
    ) -> None:
        self._chat = chat
        self._orgs = orgs
        self._members = members
        self._users = users
        self._access = access
        self._events = events
        self._activities = activities
        self._cipher = cipher
        self._media = media
        self._channels = channels
        self._attachments = attachments

    def _ctx(self, room_id: UUID, user_id: UUID, action: str):
        return open_room(
            self._chat, self._orgs, self._members, self._access,
            self._activities, room_id, user_id, action,
            channels=self._channels,
        )

    def _open_room(self, room_id: UUID, user_id: UUID, action: str):
        ctx = self._ctx(room_id, user_id, action)
        return ctx.org, ctx.floor, ctx.dm

    def _snapshot(
        self, row: OrgRoomMessage, viewer_id: UUID | None = None
    ) -> ChatMessageSnapshot:
        return message_snapshot(
            self._users,
            row,
            cipher=self._cipher,
            reactions=tally_reactions(
                self._chat.list_reactions(row.room_id, row.message_id),
                viewer_id,
            ),
            media=self._media,
        )

    def _require_manager(
        self, room_id: UUID, actor_id: UUID, action: str
    ):
        """Owner or chat:manage gate shared by pin/unpin/delete."""
        org, floor, dm = self._open_room(room_id, actor_id, action)
        if org.owner_id != actor_id and not (
            is_active_member(self._members, org.id, actor_id)
            and self._access.has_permission(org.id, actor_id, "chat:manage")
        ):
            self._access.record(
                org.id, actor_id, action, "chat", None, "denied"
            )
            raise ForbiddenError("Only org managers can do this.")
        return org, floor, dm

    def delete_message(
        self, room_id: UUID, actor_id: UUID, message_id: UUID
    ) -> None:
        org, _floor, dm = self._open_room(room_id, actor_id, "chat.delete")
        row = self._chat.get(room_id, bucket_of_uuid(message_id), message_id)
        if row is None:
            raise NotFoundError("Message not found.")
        if row.author_id != actor_id:
            if org.owner_id != actor_id and not (
                is_active_member(self._members, org.id, actor_id)
                and self._access.has_permission(
                    org.id, actor_id, "chat:manage"
                )
            ):
                self._access.record(
                    org.id, actor_id, "chat.delete", "chat",
                    message_id, "denied",
                )
                raise ForbiddenError("Only org managers can do this.")
        self._chat.delete(row)
        if self._attachments is not None:
            self._attachments.discard(
                room_id, decode_attachments(row.attachments_json)
            )
        self._chat.delete_media_index(room_id, row.bucket, message_id)
        self._chat.clear_pin(room_id, message_id)
        self._access.record(
            org.id, actor_id, "chat.delete", "chat", message_id, "allowed"
        )
        emit(self._events, room_id, "message.deleted", message_id, actor_id)
        emit_inbox(
            self._events,
            "message.deleted",
            room_id,
            org.id,
            (actor_id, dm.peer_id) if dm is not None else (),
        )

    def discard_attachment(
        self, room_id: UUID, actor_id: UUID, media_id: UUID
    ) -> None:
        """Drop one staged (unsent) attachment chip: file plus row."""
        self._open_room(room_id, actor_id, "chat.attach.discard")
        if self._attachments is None:
            raise RuntimeError("ChatAttachments is not wired.")
        self._attachments.discard_staged(room_id, actor_id, media_id)

    def mark_read(
        self, room_id: UUID, user_id: UUID, message_id: UUID
    ) -> ReadSnapshot:
        """Move the read pointer forward; a stale mark never regresses."""
        _org, _floor, _dm = self._open_room(room_id, user_id, "chat.read")
        row = self._chat.get(
            room_id, bucket_of_uuid(message_id), message_id
        )
        if row is None:
            raise NotFoundError("Message not found.")
        existing = self._chat.get_read(room_id, user_id)
        if (
            existing is not None
            and existing.last_read_message_id is not None
            and existing.last_read_message_id >= message_id
        ):
            return ReadSnapshot(
                last_read_message_id=existing.last_read_message_id,
                last_read_at=utc_aware(existing.last_read_at),
            )
        now = utcnow()
        self._chat.mark_read(room_id, user_id, message_id, now)
        # Lets every viewer's client repaint the read receipts (dm
        # double-check plus the group "seen by" list).
        emit(self._events, room_id, "message.read", message_id, user_id)
        return ReadSnapshot(
            last_read_message_id=message_id, last_read_at=now
        )

    def list_read_states(
        self, room_id: UUID, user_id: UUID
    ) -> list[RoomReadSnapshot]:
        """Every member's read pointer: the sender's 'seen by' list."""
        self._open_room(room_id, user_id, "chat.reads")
        out: list[RoomReadSnapshot] = []
        for row in self._chat.list_reads(room_id):
            if row.last_read_message_id is None:
                continue
            brief = self._users.get_brief(row.user_id)
            out.append(
                RoomReadSnapshot(
                    user_id=row.user_id,
                    user_name=(
                        brief.full_name if brief else "Unknown user"
                    ),
                    avatar_url=avatar_url(self._media, brief),
                    last_read_message_id=row.last_read_message_id,
                    last_read_at=utc_aware(row.last_read_at),
                )
            )
        return out

    def toggle_reaction(
        self, room_id: UUID, user_id: UUID, message_id: UUID, emoji: str
    ) -> ChatMessageSnapshot:
        """Toggle one palette emoji and return the message with tallies."""
        ctx = self._ctx(room_id, user_id, "chat.react")
        require_live_activity(ctx)
        channel = ctx.channel
        if channel is not None and channel.archived_at is not None:
            raise ChannelArchivedError("This channel is archived.")
        if emoji not in REACTION_EMOJIS:
            raise InvalidMemberStateError("Unsupported reaction.")
        row = self._chat.get(
            room_id, bucket_of_uuid(message_id), message_id
        )
        if row is None:
            raise NotFoundError("Message not found.")
        self._chat.set_reaction(
            room_id, message_id, user_id, emoji, utcnow()
        )
        emit(self._events, room_id, "message.reacted", message_id, user_id)
        return self._snapshot(row, user_id)

    def pin_message(
        self, room_id: UUID, actor_id: UUID, message_id: UUID
    ) -> None:
        """Managers pin one message; a room holds up to MAX_PINS pins."""
        org, _floor, _dm = self._require_manager(
            room_id, actor_id, "chat.pin"
        )
        row = self._chat.get(
            room_id, bucket_of_uuid(message_id), message_id
        )
        if row is None:
            raise NotFoundError("Message not found.")
        if (
            self._chat.get_pin(room_id, message_id) is None
            and len(self._chat.list_pins(room_id)) >= MAX_PINS
        ):
            raise PinLimitReachedError("Pin limit reached.")
        self._chat.set_pin(room_id, message_id, actor_id, utcnow())
        self._access.record(
            org.id, actor_id, "chat.pin", "chat", message_id, "allowed"
        )
        emit(self._events, room_id, "message.pinned", message_id, actor_id)

    def unpin_message(
        self, room_id: UUID, actor_id: UUID, message_id: UUID
    ) -> None:
        """Managers drop one pinned message."""
        org, _floor, _dm = self._require_manager(
            room_id, actor_id, "chat.unpin"
        )
        pin = self._chat.get_pin(room_id, message_id)
        if pin is None:
            raise NotFoundError("Message is not pinned.")
        self._chat.clear_pin(room_id, message_id)
        self._access.record(
            org.id, actor_id, "chat.unpin", "chat", message_id, "allowed"
        )
        emit(
            self._events,
            room_id,
            "message.unpinned",
            message_id,
            actor_id,
        )

    def set_mute(self, room_id: UUID, user_id: UUID, muted: bool) -> None:
        """Per-user mute flag; muted rooms still list, clients dim them."""
        self._open_room(room_id, user_id, "chat.mute")
        if muted:
            self._chat.set_mute(user_id, room_id, utcnow())
        else:
            self._chat.clear_mute(user_id, room_id)
