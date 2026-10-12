"""Org chat business rules: rooms, history paging, unread. No FastAPI."""

from __future__ import annotations

from uuid import UUID

from chat.dtos import (
    ChatMessageSnapshot,
    ChatPage,
    DmRoomSnapshot,
    ReadSnapshot,
)
from chat.helpers import bucket_of, bucket_of_uuid, next_bucket, prev_bucket
from chat.interfaces import ActivityLookup, ChatEvents, ChatStore
from chat.model import OrgRoomMessage
from core.exceptions import (
    ForbiddenError,
    InvalidMemberStateError,
    MemberNotFoundError,
    NotFoundError,
    OrgDeletedError,
)
from core.ids import uuid7
from core.security import utcnow
from orgs.interfaces import MemberRepository, OrgRepository, UserDirectory
from orgs.member_helpers import is_active_member, live_org
from rbac.interfaces import AccessControl

# A page scans back at most this many month buckets; deeper history keeps
# a resume cursor instead of one slow request. Unread counts cap here too.
MAX_SCAN_BUCKETS = 6
UNREAD_CAP = 99


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
    ) -> None:
        self._chat = chat
        self._orgs = orgs
        self._members = members
        self._users = users
        self._access = access
        self._events = events
        self._activities = activities

    def _open_room(self, room_id: UUID, user_id: UUID, action: str):
        """Resolve a room id to its org after proving access.

        Returns (org, floor_bucket): the floor stops history scans at the
        room's own creation month. A dm room resolves only for its two
        participants, so non-participants get the generic org 404.
        """
        dm = self._chat.get_dm_room(user_id, room_id)
        if dm is not None:
            org = live_org(self._orgs, dm.org_id)
            floor = bucket_of(dm.created_at)
        else:
            activity = (
                self._activities.get(room_id)
                if self._activities is not None
                else None
            )
            if activity is not None:
                org = live_org(self._orgs, activity.org_id)
                floor = bucket_of(activity.created_at)
            else:
                org = live_org(self._orgs, room_id)
                floor = bucket_of(org.created_at)
        if org.owner_id != user_id and not is_active_member(
            self._members, org.id, user_id
        ):
            self._access.record(
                org.id, user_id, action, "chat", None, "denied"
            )
            raise ForbiddenError("Only org members can do this.")
        return org, floor

    def _emit(
        self, room_id: UUID, action: str, message_id: UUID, actor_id: UUID
    ) -> None:
        try:
            self._events.message_changed(room_id, action, message_id, actor_id)
        except Exception:  # noqa: BLE001 - realtime is best-effort
            pass

    def _snapshot(self, row: OrgRoomMessage) -> ChatMessageSnapshot:
        brief = self._users.get_brief(row.author_id)
        return ChatMessageSnapshot(
            message_id=row.message_id,
            room_id=row.room_id,
            author_id=row.author_id,
            author_name=brief.full_name if brief else "Unknown user",
            body=row.body or "",
            created_at=row.created_at,
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
        _org, floor = self._open_room(room_id, viewer_id, "chat.list")
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
        return ChatPage(
            items=[
                self._snapshot(row) for row in reversed(collected)
            ],
            next_cursor=next_cursor,
            unread=self._unread(room_id, floor, last_read),
            last_read_message_id=last_read,
        )

    def _unread(
        self, room_id: UUID, floor: str, last_read: UUID | None
    ) -> int:
        """Messages newer than the read pointer, capped at UNREAD_CAP."""
        start = bucket_of_uuid(last_read) if last_read is not None else floor
        current = bucket_of(utcnow())
        bucket, total = start, 0
        while bucket <= current and total < UNREAD_CAP:
            total += self._chat.count_after(room_id, bucket, last_read)
            last_read = None  # only the first bucket counts from the pointer
            bucket = next_bucket(bucket)
        return min(total, UNREAD_CAP)

    def send_message(
        self, room_id: UUID, actor_id: UUID, body: str
    ) -> ChatMessageSnapshot:
        org, _floor = self._open_room(room_id, actor_id, "chat.send")
        now = utcnow()
        message_id = uuid7()
        row = self._chat.create(
            room_id, bucket_of(now), message_id, actor_id, body, now
        )
        self._access.record(
            org.id, actor_id, "chat.send", "chat", message_id, "allowed"
        )
        # Own messages never inflate the sender's unread badge.
        self._chat.mark_read(room_id, actor_id, message_id, now)
        self._emit(room_id, "message.created", message_id, actor_id)
        return self._snapshot(row)

    def delete_message(
        self, room_id: UUID, actor_id: UUID, message_id: UUID
    ) -> None:
        org, _floor = self._open_room(room_id, actor_id, "chat.delete")
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
        self._access.record(
            org.id, actor_id, "chat.delete", "chat", message_id, "allowed"
        )
        self._emit(room_id, "message.deleted", message_id, actor_id)

    def mark_read(
        self, room_id: UUID, user_id: UUID, message_id: UUID
    ) -> ReadSnapshot:
        """Move the read pointer forward; a stale mark never regresses."""
        self._open_room(room_id, user_id, "chat.read")
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
                last_read_at=existing.last_read_at,
            )
        now = utcnow()
        self._chat.mark_read(room_id, user_id, message_id, now)
        return ReadSnapshot(
            last_read_message_id=message_id, last_read_at=now
        )

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
        brief = self._users.get_brief(peer_id)
        return DmRoomSnapshot(
            room_id=pair.room_id,
            org_id=org_id,
            peer_id=peer_id,
            peer_name=brief.full_name if brief else "Unknown user",
            created_at=pair.created_at,
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
                    created_at=row.created_at,
                )
            )
        return out
