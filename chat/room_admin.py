"""Per-room moderation and read state: delete, react, pin, mute, read."""

from __future__ import annotations

from uuid import UUID

from chat.dtos import ChatMessageSnapshot, ReadSnapshot
from chat.helpers import (
    REACTION_EMOJIS,
    bucket_of_uuid,
    message_snapshot,
    tally_reactions,
)
from chat.interfaces import ActivityLookup, ChatEvents, ChatStore
from chat.model import OrgRoomMessage
from chat.rooms import emit, emit_inbox, open_room
from core.exceptions import (
    ForbiddenError,
    InvalidMemberStateError,
    NotFoundError,
)
from core.security import utc_aware, utcnow
from orgs.interfaces import MemberRepository, OrgRepository, UserDirectory
from orgs.member_helpers import is_active_member
from rbac.interfaces import AccessControl


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
    ) -> None:
        self._chat = chat
        self._orgs = orgs
        self._members = members
        self._users = users
        self._access = access
        self._events = events
        self._activities = activities
        self._cipher = cipher

    def _open_room(self, room_id: UUID, user_id: UUID, action: str):
        ctx = open_room(
            self._chat, self._orgs, self._members, self._access,
            self._activities, room_id, user_id, action,
        )
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
        pin = self._chat.get_pin(room_id)
        if pin is not None and pin.message_id == message_id:
            self._chat.clear_pin(room_id)
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

    def mark_read(
        self, room_id: UUID, user_id: UUID, message_id: UUID
    ) -> ReadSnapshot:
        """Move the read pointer forward; a stale mark never regresses."""
        _org, _floor, dm = self._open_room(room_id, user_id, "chat.read")
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
        if dm is not None:
            # Lets the peer's client repaint the double-check receipt.
            emit(self._events, room_id, "message.read", message_id, user_id)
        return ReadSnapshot(
            last_read_message_id=message_id, last_read_at=now
        )

    def toggle_reaction(
        self, room_id: UUID, user_id: UUID, message_id: UUID, emoji: str
    ) -> ChatMessageSnapshot:
        """Toggle one palette emoji and return the message with tallies."""
        self._open_room(room_id, user_id, "chat.react")
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
        """Managers pin one message; the slot holds only the latest pin."""
        org, _floor, _dm = self._require_manager(
            room_id, actor_id, "chat.pin"
        )
        row = self._chat.get(
            room_id, bucket_of_uuid(message_id), message_id
        )
        if row is None:
            raise NotFoundError("Message not found.")
        self._chat.set_pin(room_id, message_id, actor_id, utcnow())
        self._access.record(
            org.id, actor_id, "chat.pin", "chat", message_id, "allowed"
        )
        emit(self._events, room_id, "message.pinned", message_id, actor_id)

    def unpin_message(self, room_id: UUID, actor_id: UUID) -> None:
        """Managers clear the pinned slot."""
        org, _floor, _dm = self._require_manager(
            room_id, actor_id, "chat.unpin"
        )
        pin = self._chat.get_pin(room_id)
        self._chat.clear_pin(room_id)
        self._access.record(
            org.id, actor_id, "chat.unpin", "chat", None, "allowed"
        )
        if pin is not None:
            emit(
                self._events,
                room_id,
                "message.unpinned",
                pin.message_id,
                actor_id,
            )

    def set_mute(self, room_id: UUID, user_id: UUID, muted: bool) -> None:
        """Per-user mute flag; muted rooms still list, clients dim them."""
        self._open_room(room_id, user_id, "chat.mute")
        if muted:
            self._chat.set_mute(user_id, room_id, utcnow())
        else:
            self._chat.clear_mute(user_id, room_id)
