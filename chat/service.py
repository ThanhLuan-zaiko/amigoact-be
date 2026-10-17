"""Org chat business rules: rooms, history paging, unread. No FastAPI."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from chat.composer import ChatComposer
    from chat.room_admin import ChatRoomAdmin

from chat.dtos import (
    ChatMessageSnapshot,
    ChatPage,
    DmRoomSnapshot,
    ReadSnapshot,
)
from chat.helpers import (
    MAX_SCAN_BUCKETS,
    bucket_of,
    bucket_of_uuid,
    prev_bucket,
    tally_reactions,
    unread_count,
)
from chat.helpers import message_snapshot
from chat.interfaces import ActivityLookup, ChatEvents, ChatStore
from chat.model import OrgRoomMessage
from chat.room_admin import ChatRoomAdmin
from chat.rooms import emit, emit_inbox, open_room
from core.exceptions import (
    ForbiddenError,
    InvalidMemberStateError,
    MemberNotFoundError,
    NotFoundError,
    OrgDeletedError,
)
from core.ids import uuid7
from core.security import utc_aware, utcnow
from orgs.interfaces import MemberRepository, OrgRepository, UserDirectory
from orgs.member_helpers import is_active_member, live_org
from rbac.interfaces import AccessControl


class ChatService:
    """Room rules: members chat, authors or chat:manage moderate.

    A room id is the org id (general), an activity id (activity room), or
    a dm room id resolvable only through a participant inbox row. Every
    operation resolves the room first, then enforces org membership.
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
        composer: "ChatComposer | None" = None,
        admin: "ChatRoomAdmin | None" = None,
        cipher=None,  # noqa: ANN001
    ) -> None:
        self._chat = chat
        self._orgs = orgs
        self._members = members
        self._users = users
        self._access = access
        self._events = events
        self._activities = activities
        self._composer = composer
        # Room state ops default to a sibling service over the same ports;
        # tests may inject a custom one through the admin parameter.
        self._admin = admin or ChatRoomAdmin(
            chat, orgs, members, users, access, events, activities, cipher
        )
        self._cipher = cipher

    def _open_room(self, room_id: UUID, user_id: UUID, action: str):
        """(org, floor_bucket, dm_row) after proving access — see rooms.py."""
        ctx = open_room(
            self._chat, self._orgs, self._members, self._access,
            self._activities, room_id, user_id, action,
        )
        return ctx.org, ctx.floor, ctx.dm

    def _emit(
        self, room_id: UUID, action: str, message_id: UUID, actor_id: UUID
    ) -> None:
        emit(self._events, room_id, action, message_id, actor_id)

    def _emit_inbox(
        self,
        action: str,
        room_id: UUID,
        org_id: UUID,
        peer_ids: tuple[UUID, ...] = (),
    ) -> None:
        emit_inbox(self._events, action, room_id, org_id, peer_ids)

    def _snapshot(
        self, row: OrgRoomMessage, viewer_id: UUID | None = None
    ) -> ChatMessageSnapshot:
        reactions = tally_reactions(
            self._chat.list_reactions(row.room_id, row.message_id),
            viewer_id,
        )
        return message_snapshot(
            self._users, row, cipher=self._cipher, reactions=reactions
        )

    def can_access(self, room_id: UUID, user_id: UUID) -> bool:
        """Realtime ACL port: mirrors _open_room without raising."""
        try:
            self._open_room(room_id, user_id, "chat.subscribe")
            return True
        except (NotFoundError, ForbiddenError, OrgDeletedError):
            return False

    def list_messages(
        self,
        room_id: UUID,
        viewer_id: UUID,
        *,
        limit: int = 30,
        cursor: str | None = None,
    ) -> ChatPage:
        """Newest page first; the cursor resumes the bucket walk.

        A normal cursor is the oldest message id seen. When a request only
        finds empty buckets the resume marker 'bb:{YYYYMM}' continues the
        walk one month earlier, so gaps never stall pagination.
        """
        _org, floor, dm = self._open_room(room_id, viewer_id, "chat.list")
        upper: UUID | None = None
        if cursor and cursor.startswith("bb:"):
            bucket = cursor[3:9]
            if len(bucket) != 6 or not bucket.isdigit():
                bucket = bucket_of(utcnow())
        elif cursor:
            try:
                upper = UUID(cursor)
                bucket = bucket_of_uuid(upper)
            except ValueError:
                bucket = bucket_of(utcnow())
        else:
            bucket = bucket_of(utcnow())

        collected: list[OrgRoomMessage] = []
        hit_floor = False
        for _ in range(MAX_SCAN_BUCKETS):
            rows = self._chat.list_before(
                room_id, bucket, upper, limit - len(collected)
            )
            collected.extend(rows)
            upper = None  # the bound only applies to the first bucket
            if len(collected) >= limit:
                break
            if bucket <= floor:
                hit_floor = True
                break
            bucket = prev_bucket(bucket)

        if len(collected) >= limit and collected:
            next_cursor: str | None = str(collected[-1].message_id)
        elif hit_floor or bucket <= floor:
            next_cursor = None
        else:
            next_cursor = f"bb:{prev_bucket(bucket)}"

        read_row = self._chat.get_read(room_id, viewer_id)
        last_read = (
            read_row.last_read_message_id if read_row is not None else None
        )
        peer_last_read: UUID | None = None
        if dm is not None:
            peer_row = self._chat.get_read(room_id, dm.peer_id)
            if peer_row is not None:
                peer_last_read = peer_row.last_read_message_id
        pin = self._chat.get_pin(room_id)
        pinned = None
        if pin is not None:
            pinned_row = self._chat.get(
                room_id, bucket_of_uuid(pin.message_id), pin.message_id
            )
            if pinned_row is not None:
                pinned = self._snapshot(pinned_row, viewer_id)
        muted = any(
            row.room_id == room_id
            for row in self._chat.list_mutes(viewer_id)
        )
        return ChatPage(
            items=[
                self._snapshot(row, viewer_id) for row in reversed(collected)
            ],
            next_cursor=next_cursor,
            unread=unread_count(self._chat, room_id, floor, last_read),
            last_read_message_id=last_read,
            peer_last_read_message_id=peer_last_read,
            pinned=pinned,
            muted=muted,
        )

    def send_message(
        self,
        room_id: UUID,
        actor_id: UUID,
        body: str,
        *,
        reply_to_id: UUID | None = None,
        attachment_ids: tuple[UUID, ...] | list[UUID] = (),
    ) -> ChatMessageSnapshot:
        """Write path lives on ChatComposer; kept here for DI parity."""
        if self._composer is None:
            raise RuntimeError("ChatComposer is not wired.")
        return self._composer.send_message(
            room_id, actor_id, body,
            reply_to_id=reply_to_id, attachment_ids=attachment_ids,
        )

    def edit_message(
        self, room_id: UUID, actor_id: UUID, message_id: UUID, body: str
    ) -> ChatMessageSnapshot:
        if self._composer is None:
            raise RuntimeError("ChatComposer is not wired.")
        return self._composer.edit_message(room_id, actor_id, message_id, body)

    def create_attachment(
        self,
        room_id: UUID,
        actor_id: UUID,
        filename: str,
        mime: str,
        content: bytes,
    ):
        if self._composer is None:
            raise RuntimeError("ChatComposer is not wired.")
        return self._composer.create_attachment(
            room_id, actor_id, filename, mime, content
        )

    def delete_message(
        self, room_id: UUID, actor_id: UUID, message_id: UUID
    ) -> None:
        self._admin.delete_message(room_id, actor_id, message_id)

    def mark_read(
        self, room_id: UUID, user_id: UUID, message_id: UUID
    ) -> ReadSnapshot:
        return self._admin.mark_read(room_id, user_id, message_id)

    def toggle_reaction(
        self, room_id: UUID, user_id: UUID, message_id: UUID, emoji: str
    ) -> ChatMessageSnapshot:
        return self._admin.toggle_reaction(
            room_id, user_id, message_id, emoji
        )

    def pin_message(
        self, room_id: UUID, actor_id: UUID, message_id: UUID
    ) -> None:
        self._admin.pin_message(room_id, actor_id, message_id)

    def unpin_message(self, room_id: UUID, actor_id: UUID) -> None:
        self._admin.unpin_message(room_id, actor_id)

    def set_mute(self, room_id: UUID, user_id: UUID, muted: bool) -> None:
        self._admin.set_mute(room_id, user_id, muted)

    def open_dm(
        self, org_id: UUID, actor_id: UUID, peer_id: UUID
    ) -> DmRoomSnapshot:
        """Find or create the dm room between two members of one org."""
        org = live_org(self._orgs, org_id)
        if org.owner_id != actor_id and not is_active_member(
            self._members, org_id, actor_id
        ):
            self._access.record(
                org_id, actor_id, "chat.dm", "chat", None, "denied"
            )
            raise ForbiddenError("Only org members can do this.")
        if peer_id == actor_id:
            raise InvalidMemberStateError("Cannot open a chat with yourself.")
        if peer_id != org.owner_id and not is_active_member(
            self._members, org_id, peer_id
        ):
            raise MemberNotFoundError("Member not found.")
        user_lo, user_hi = sorted((actor_id, peer_id))
        pair = self._chat.create_dm_room(
            uuid7(), org_id, user_lo, user_hi, utcnow()
        )
        # Both inboxes gain the row at once, so both participants hear it.
        self._emit_inbox(
            "dm.opened", pair.room_id, org_id, (actor_id, peer_id)
        )
        brief = self._users.get_brief(peer_id)
        return DmRoomSnapshot(
            room_id=pair.room_id,
            org_id=org_id,
            peer_id=peer_id,
            peer_name=brief.full_name if brief else "Unknown user",
            created_at=utc_aware(pair.created_at),
        )

    def list_dm_rooms(
        self, org_id: UUID, user_id: UUID
    ) -> list[DmRoomSnapshot]:
        """The caller's dm inbox inside one org, oldest room first."""
        org = live_org(self._orgs, org_id)
        if org.owner_id != user_id and not is_active_member(
            self._members, org_id, user_id
        ):
            self._access.record(
                org_id, user_id, "chat.dm.list", "chat", None, "denied"
            )
            raise ForbiddenError("Only org members can do this.")
        rows = [
            row
            for row in self._chat.list_dm_rooms(user_id)
            if row.org_id == org_id
        ]
        rows.sort(key=lambda row: row.room_id)
        out: list[DmRoomSnapshot] = []
        for row in rows:
            brief = self._users.get_brief(row.peer_id)
            out.append(
                DmRoomSnapshot(
                    room_id=row.room_id,
                    org_id=org_id,
                    peer_id=row.peer_id,
                    peer_name=brief.full_name if brief else "Unknown user",
                    created_at=utc_aware(row.created_at),
                )
            )
        return out
