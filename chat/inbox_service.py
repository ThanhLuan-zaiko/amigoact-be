"""Cross-org inbox summaries: every room a member can open, freshest first.

Authorization is inherent: the list is derived from the caller's own
memberships and dm partitions, so no per-room ACL pass is needed. Read
math (buckets, unread, preview peek) lives in chat.helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from chat.dtos import InboxRoomSnapshot
from chat.helpers import bucket_of, peek_last_message, unread_count
from chat.channel_interfaces import ChannelStore
from chat.interfaces import ActivityLookup, ChatStore
from chat.rooms import linked_activity_deleted
from core.security import utc_aware, utcnow
from orgs.interfaces import (
    MediaRepository,
    MemberRepository,
    OrgRepository,
    UserDirectory,
)
from rbac.interfaces import AccessControl

# Inbox preview bodies stay short: the rail renders one line per room.
PREVIEW_LEN = 160
# Activities enumerate at most this many rooms per org per inbox call.
ACTIVITY_ROOM_LIMIT = 50


@dataclass(frozen=True)
class _RoomRef:
    """One room a member can open, before its summary is computed."""

    room_id: UUID
    kind: str
    org_id: UUID
    org_name: str
    org_slug: str
    title: str
    peer_id: UUID | None
    avatar_url: str | None
    created_at: datetime | None
    peer_last_seen_at: datetime | None = None
    # Channel rows only: post gate + display label for the rail.
    post_policy: str | None = None
    channel_kind: str | None = None
    # Sub-thread rows only: parent room + optional linked activity.
    parent_room_id: UUID | None = None
    activity_id: UUID | None = None
    activity_deleted: bool = False


class ChatInboxService:
    """Telegram-style inbox: general + activity + dm + channel rows."""

    def __init__(
        self,
        chat: ChatStore,
        orgs: OrgRepository,
        members: MemberRepository,
        users: UserDirectory,
        activities: ActivityLookup | None = None,
        media: MediaRepository | None = None,
        cipher=None,  # noqa: ANN001
        channels: ChannelStore | None = None,
        access: AccessControl | None = None,
    ) -> None:
        self._chat = chat
        self._orgs = orgs
        self._members = members
        self._users = users
        self._activities = activities
        self._media = media
        self._cipher = cipher
        self._channels = channels
        self._access = access

    def _decrypt(self, text: str) -> str:
        return self._cipher.decrypt(text) if self._cipher else text

    def _media_url(self, asset_id: UUID | None) -> str | None:
        """Resolve a logo/avatar asset to its /media/ URL like public_service."""
        if asset_id is None or self._media is None:
            return None
        asset = self._media.get_asset(asset_id)
        return f"/media/{asset.file_url}" if asset is not None else None

    def _active_orgs(self, user_id: UUID) -> dict[UUID, object]:
        """Live orgs where the caller holds an active link or is owner."""
        orgs: dict[UUID, object] = {}
        for link in self._members.list_links_by_user(user_id):
            org = self._orgs.get_by_id(link.org_id)
            if org is None or getattr(org, "deleted_at", None) is not None:
                continue
            active = (getattr(link, "status", "active") or "active") == (
                "active"
            )
            if active or org.owner_id == user_id:
                orgs[org.id] = org
        return orgs

    def _room_refs(self, user_id: UUID) -> list[_RoomRef]:
        """Every room the caller can open: general + activity + dm."""
        orgs = self._active_orgs(user_id)
        refs: list[_RoomRef] = []
        for org in orgs.values():
            org_logo = self._media_url(getattr(org, "logo_media_id", None))
            refs.append(
                _RoomRef(
                    room_id=org.id,
                    kind="general",
                    org_id=org.id,
                    org_name=org.name,
                    org_slug=getattr(org, "slug", "") or "",
                    title=org.name,
                    peer_id=None,
                    avatar_url=org_logo,
                    created_at=getattr(org, "created_at", None),
                )
            )
            if self._activities is None:
                continue
            for act in self._activities.list_by_org(
                org.id, limit=ACTIVITY_ROOM_LIMIT
            ):
                refs.append(
                    _RoomRef(
                        room_id=act.id,
                        kind="activity",
                        org_id=org.id,
                        org_name=org.name,
                        org_slug=getattr(org, "slug", "") or "",
                        title=act.title,
                        peer_id=None,
                        avatar_url=org_logo,
                        created_at=getattr(act, "created_at", None),
                    )
                )
        for ref in self._channel_refs(user_id, orgs):
            refs.append(ref)
        for row in self._chat.list_dm_rooms(user_id):
            org = orgs.get(row.org_id)
            if org is None:
                # Left/deleted orgs close their dm rooms too (_open_room
                # enforces the same membership gate on every operation).
                continue
            brief = self._users.get_brief(row.peer_id)
            refs.append(
                _RoomRef(
                    room_id=row.room_id,
                    kind="dm",
                    org_id=org.id,
                    org_name=org.name,
                    org_slug=getattr(org, "slug", "") or "",
                    title=brief.full_name if brief else "Unknown user",
                    peer_id=row.peer_id,
                    avatar_url=self._media_url(
                        getattr(brief, "avatar_media_id", None)
                    ),
                    created_at=row.created_at,
                    peer_last_seen_at=utc_aware(
                        getattr(brief, "last_seen_at", None)
                    ) if brief else None,
                )
            )
        return refs

    def _channel_refs(
        self, user_id: UUID, orgs: dict[UUID, object]
    ) -> list[_RoomRef]:
        """Live channels visible to the caller.

        Org-wide channels appear for every active member; restricted
        ones need a roster seat or a manager role (owner/chat:manage).
        """
        if self._channels is None:
            return []
        seats = {
            row.channel_id
            for row in self._channels.list_channel_memberships(user_id)
        }
        refs: list[_RoomRef] = []
        for org in orgs.values():
            manager = org.owner_id == user_id or (
                self._access is not None
                and self._access.has_permission(
                    org.id, user_id, "chat:manage"
                )
            )
            org_logo = self._media_url(getattr(org, "logo_media_id", None))
            rows = self._channels.list_channels(org.id)
            by_id = {row.channel_id: row for row in rows}
            for row in rows:
                if row.archived_at is not None:
                    continue
                # A sub-thread gates through its parent channel's
                # roster (seats live there, never on the thread).
                gate = by_id.get(
                    getattr(row, "parent_room_id", None) or row.channel_id,
                    row,
                )
                if (
                    gate.visibility == "restricted"
                    and not manager
                    and gate.channel_id not in seats
                ):
                    continue
                refs.append(
                    _RoomRef(
                        room_id=row.channel_id,
                        kind="channel",
                        org_id=org.id,
                        org_name=org.name,
                        org_slug=getattr(org, "slug", "") or "",
                        title=row.name,
                        peer_id=None,
                        avatar_url=org_logo,
                        created_at=getattr(row, "created_at", None),
                        post_policy=row.post_policy,
                        channel_kind=row.kind,
                        parent_room_id=getattr(
                            row, "parent_room_id", None
                        ),
                        activity_id=getattr(row, "activity_id", None),
                        activity_deleted=linked_activity_deleted(
                            self._activities,
                            getattr(row, "activity_id", None),
                        ),
                    )
                )
        return refs

    def list_inbox(self, user_id: UUID) -> list[InboxRoomSnapshot]:
        """Every openable room summarized, sorted by latest activity."""
        mutes = {
            row.room_id for row in self._chat.list_mutes(user_id)
        }
        out: list[InboxRoomSnapshot] = []
        for ref in self._room_refs(user_id):
            created = utc_aware(ref.created_at) or utcnow()
            floor = bucket_of(created)
            last = peek_last_message(self._chat, ref.room_id, floor)
            read_row = self._chat.get_read(ref.room_id, user_id)
            last_read = (
                read_row.last_read_message_id
                if read_row is not None
                else None
            )
            if last is not None:
                brief = self._users.get_brief(last.author_id)
                last_id = last.message_id
                last_body = self._decrypt(last.body or "")[:PREVIEW_LEN]
                last_name = brief.full_name if brief else "Unknown user"
                last_at = utc_aware(last.created_at)
            else:
                last_id = last_body = last_name = last_at = None
            out.append(
                InboxRoomSnapshot(
                    room_id=ref.room_id,
                    kind=ref.kind,
                    org_id=ref.org_id,
                    org_name=ref.org_name,
                    org_slug=ref.org_slug,
                    title=ref.title,
                    peer_id=ref.peer_id,
                    last_message_id=last_id,
                    last_body=last_body,
                    last_author_name=last_name,
                    last_at=last_at,
                    unread=unread_count(
                        self._chat, ref.room_id, floor, last_read
                    ),
                    sort_at=last_at or created,
                    avatar_url=ref.avatar_url,
                    peer_last_seen_at=ref.peer_last_seen_at,
                    muted=ref.room_id in mutes,
                    post_policy=ref.post_policy,
                    channel_kind=ref.channel_kind,
                    parent_room_id=ref.parent_room_id,
                    activity_id=ref.activity_id,
                    activity_deleted=ref.activity_deleted,
                )
            )
        out.sort(key=lambda item: item.sort_at, reverse=True)
        return out
