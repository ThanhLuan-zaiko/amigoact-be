"""Shared-media listing: the room info panel's image/video/file/link tabs.

Read path mirrors ChatService.list_messages (same bucket walk, same
'bb:' gap cursor), but reads the org_room_media index instead of the
message partitions so a tab never scans plain-text rows. Link rows keep
the body's ciphertext at rest and are decrypted on the way out.
"""

from __future__ import annotations

from uuid import UUID

from chat.dtos import (
    SharedAuthorSnapshot,
    SharedItemSnapshot,
    SharedMediaPage,
)
from chat.helpers import (
    MAX_ITEMS_PER_MESSAGE,
    MAX_SCAN_BUCKETS,
    avatar_url,
    bucket_of,
    bucket_of_uuid,
    prev_bucket,
)
from chat.channel_interfaces import ChannelStore
from chat.interfaces import ActivityLookup, ChatStore
from chat.rooms import open_room
from core.security import utc_aware, utcnow
from orgs.interfaces import (
    MediaRepository,
    MemberRepository,
    OrgRepository,
    UserDirectory,
)
from rbac.interfaces import AccessControl


class ChatMediaService:
    """Room-tab reads over the shared-item index; no writes live here."""

    def __init__(
        self,
        chat: ChatStore,
        orgs: OrgRepository,
        members: MemberRepository,
        users: UserDirectory,
        access: AccessControl,
        activities: ActivityLookup | None = None,
        cipher=None,  # noqa: ANN001
        media: MediaRepository | None = None,
        channels: ChannelStore | None = None,
    ) -> None:
        self._chat = chat
        self._orgs = orgs
        self._members = members
        self._users = users
        self._access = access
        self._activities = activities
        self._cipher = cipher
        self._media = media
        self._channels = channels

    def _decrypt(self, text: str) -> str:
        return self._cipher.decrypt(text) if self._cipher else text

    def _open(self, room_id: UUID, viewer_id: UUID):
        ctx = open_room(
            self._chat, self._orgs, self._members, self._access,
            self._activities, room_id, viewer_id, "chat.media",
            channels=self._channels,
        )
        return ctx.floor

    def _snapshot(self, row) -> SharedItemSnapshot:  # noqa: ANN001
        brief = self._users.get_brief(row.author_id)
        url = row.url if row.kind != "link" else self._decrypt(row.url)
        return SharedItemSnapshot(
            message_id=row.message_id,
            kind=row.kind,
            media_id=row.media_id,
            url=url,
            mime=row.mime or "",
            name=row.name or "",
            size_bytes=int(row.size_bytes or 0),
            author_id=row.author_id,
            author_name=brief.full_name if brief else "Unknown user",
            author_avatar_url=avatar_url(self._media, brief),
            created_at=utc_aware(row.created_at),
        )

    def list_shared_media(
        self,
        room_id: UUID,
        viewer_id: UUID,
        *,
        kind: str,
        limit: int = 30,
        cursor: str | None = None,
        author_id: UUID | None = None,
    ) -> SharedMediaPage:
        """Newest-first page of one tab.

        A normal cursor is '{message_id}.{item_index}' of the last item
        served; the 'bb:{YYYYMM}' marker resumes an empty-bucket walk one
        month earlier, exactly like the message history cursor.
        """
        floor = self._open(room_id, viewer_id)
        upper_mid: UUID | None = None
        upper_idx: int = -1
        bucket = bucket_of(utcnow())
        if cursor and cursor.startswith("bb:"):
            tail = cursor[3:9]
            if len(tail) == 6 and tail.isdigit():
                bucket = tail
        elif cursor:
            mid, _, idx = cursor.partition(".")
            try:
                upper_mid = UUID(mid)
                upper_idx = int(idx)
                bucket = bucket_of_uuid(upper_mid)
            except ValueError:
                upper_mid, upper_idx = None, -1

        collected = []
        hit_floor = False
        for _ in range(MAX_SCAN_BUCKETS):
            rows = self._chat.list_media_page(
                room_id, bucket, kind, upper_mid,
                limit + MAX_ITEMS_PER_MESSAGE, author_id,
            )
            for row in rows:
                if (
                    upper_mid is not None
                    and row.message_id == upper_mid
                    and row.item_index <= upper_idx
                ):
                    continue
                collected.append(row)
                if len(collected) >= limit:
                    break
            if len(collected) >= limit:
                break
            upper_mid, upper_idx = None, -1
            if bucket <= floor:
                hit_floor = True
                break
            bucket = prev_bucket(bucket)

        if len(collected) >= limit:
            last = collected[-1]
            next_cursor: str | None = f"{last.message_id}.{last.item_index}"
        elif hit_floor or bucket <= floor:
            next_cursor = None
        else:
            next_cursor = f"bb:{prev_bucket(bucket)}"
        return SharedMediaPage(
            items=[self._snapshot(row) for row in collected],
            next_cursor=next_cursor,
        )

    def list_media_authors(
        self, room_id: UUID, viewer_id: UUID
    ) -> list[SharedAuthorSnapshot]:
        """Senders offered by the info panel's filter: any member who
        still has at least one indexed item, newest activity first."""
        self._open(room_id, viewer_id)
        rows = self._chat.list_media_authors(room_id)
        grouped: dict[UUID, dict] = {}
        for row in rows:
            slot = grouped.setdefault(
                row.author_id, {"kinds": set(), "last_at": None}
            )
            slot["kinds"].add(row.kind)
            last_at = utc_aware(row.last_at)
            if slot["last_at"] is None or last_at > slot["last_at"]:
                slot["last_at"] = last_at
        out: list[SharedAuthorSnapshot] = []
        for author_id, slot in grouped.items():
            brief = self._users.get_brief(author_id)
            out.append(
                SharedAuthorSnapshot(
                    author_id=author_id,
                    author_name=brief.full_name if brief else "Unknown user",
                    author_avatar_url=avatar_url(self._media, brief),
                    kinds=tuple(sorted(slot["kinds"])),
                    last_at=slot["last_at"],
                )
            )
        out.sort(key=lambda a: (a.author_name.casefold(), str(a.author_id)))
        return out
