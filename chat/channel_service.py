"""Named-channel lifecycle: create, list, update, archive, roster.

channel_id doubles as the room id (open_room resolves it), so this
service only owns channel metadata; posting gates live in the composer.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from chat.dtos import ChannelMemberSnapshot, ChannelSnapshot
from chat.channel_interfaces import ChannelStore
from chat.interfaces import ChatEvents
from chat.rooms import emit_inbox
from core.exceptions import (
    ChannelArchivedError,
    ChannelNameTakenError,
    ChannelNotFoundError,
    ForbiddenError,
    InvalidChannelStateError,
    MemberNotFoundError,
    NotFoundError,
)
from core.security import utc_aware, utcnow
from orgs.interfaces import (
    MediaRepository,
    MemberRepository,
    OrgRepository,
    UserDirectory,
)
from orgs.member_helpers import is_active_member, live_org
from orgs.model import Organization
from rbac.interfaces import AccessControl

CHANNEL_NAME_MAX = 80
CHANNEL_TOPIC_MAX = 200


class ChannelService:
    """Channel CRUD plus restricted-roster management (managers only)."""

    def __init__(
        self,
        channels: ChannelStore,
        orgs: OrgRepository,
        members: MemberRepository,
        users: UserDirectory,
        access: AccessControl,
        events: ChatEvents,
        media: MediaRepository | None = None,
    ) -> None:
        self._channels = channels
        self._orgs = orgs
        self._members = members
        self._users = users
        self._access = access
        self._events = events
        self._media = media

    def _manager(self, org: Organization, actor_id: UUID) -> bool:
        """True for org owner or a chat:manage holder."""
        return org.owner_id == actor_id or self._access.has_permission(
            org.id, actor_id, "chat:manage"
        )

    def _require_manager(self, org: Organization, actor_id: UUID) -> None:
        if not self._manager(org, actor_id):
            self._access.record(
                org.id, actor_id, "channel.manage", "chat",
                None, "denied",
            )
            raise ForbiddenError("Only chat managers can do this.")

    def _get(self, org_id: UUID, channel_id: UUID):
        row = self._channels.get_channel_in_org(org_id, channel_id)
        if row is None:
            raise ChannelNotFoundError("Channel not found.")
        return row

    @staticmethod
    def _snap(row) -> ChannelSnapshot:  # noqa: ANN001
        return ChannelSnapshot(
            channel_id=row.channel_id,
            org_id=row.org_id,
            name=row.name,
            topic=row.topic or "",
            kind=row.kind,
            post_policy=row.post_policy,
            visibility=row.visibility,
            created_by=row.created_by,
            created_at=utc_aware(row.created_at),
            archived_at=utc_aware(row.archived_at),
        )

    def _avatar_url(self, asset_id: UUID | None) -> str | None:
        if asset_id is None or self._media is None:
            return None
        asset = self._media.get_asset(asset_id)
        return f"/media/{asset.file_url}" if asset is not None else None

    def _fan(self, action: str, channel_id: UUID, org_id: UUID) -> None:
        emit_inbox(self._events, action, channel_id, org_id)

    def list_channels(
        self, org_id: UUID, viewer_id: UUID
    ) -> list[ChannelSnapshot]:
        """Visible channels: org-wide live ones, plus restricted rooms
        the viewer sits on. Managers additionally see archived rows so
        they can restore them."""
        org = live_org(self._orgs, org_id)
        if org.owner_id != viewer_id and not is_active_member(
            self._members, org.id, viewer_id
        ):
            raise ForbiddenError("Only org members can do this.")
        manager = self._manager(org, viewer_id)
        seats = {
            row.channel_id
            for row in self._channels.list_channel_memberships(viewer_id)
        }
        return [
            self._snap(row)
            for row in self._channels.list_channels(org_id)
            if (row.archived_at is None or manager)
            and (
                row.visibility != "restricted"
                or manager
                or row.channel_id in seats
            )
        ]

    def create_channel(
        self,
        org_id: UUID,
        actor_id: UUID,
        name: str,
        topic: str,
        kind: str,
        post_policy: str,
        visibility: str,
        member_ids: list[UUID] | tuple[UUID, ...] = (),
    ) -> ChannelSnapshot:
        org = live_org(self._orgs, org_id)
        self._require_manager(org, actor_id)
        name = (name or "").strip()
        if not name or len(name) > CHANNEL_NAME_MAX:
            raise InvalidChannelStateError(
                f"Channel name needs 1-{CHANNEL_NAME_MAX} characters."
            )
        topic = (topic or "").strip()[:CHANNEL_TOPIC_MAX]
        now = utcnow()
        row = self._channels.create_channel(
            org_id, name, topic, kind, post_policy, visibility,
            actor_id, now,
        )
        if row is None:
            raise ChannelNameTakenError("A channel with that name exists.")
        if visibility == "restricted":
            self._seed_seats(row, org, actor_id, tuple(member_ids), now)
        self._fan("channel.created", row.channel_id, org_id)
        self._access.record(
            org_id, actor_id, "channel.create", "chat",
            row.channel_id, "allowed",
        )
        return self._snap(row)

    def _seed_seats(
        self,
        row,
        org: Organization,
        actor_id: UUID,
        member_ids: tuple[UUID, ...],
        now: datetime,
    ) -> None:
        """Creator plus invited roster for a restricted channel."""
        for user_id in {actor_id, *member_ids}:
            if user_id != org.owner_id and not is_active_member(
                self._members, row.org_id, user_id
            ):
                raise MemberNotFoundError(
                    "Channel seats require active org members."
                )
            self._channels.add_channel_member(
                row.channel_id, row.org_id, user_id, actor_id, now
            )

    def update_channel(
        self,
        org_id: UUID,
        channel_id: UUID,
        actor_id: UUID,
        *,
        name: str | None = None,
        topic: str | None = None,
        kind: str | None = None,
        post_policy: str | None = None,
        visibility: str | None = None,
        archived: bool | None = None,
    ) -> ChannelSnapshot:
        org = live_org(self._orgs, org_id)
        self._require_manager(org, actor_id)
        row = self._get(org_id, channel_id)
        now = utcnow()
        release: str | None = None
        if name is not None:
            clean = name.strip()
            if not clean or len(clean) > CHANNEL_NAME_MAX:
                raise InvalidChannelStateError(
                    f"Channel name needs 1-{CHANNEL_NAME_MAX} characters."
                )
            if clean.casefold() != row.name_folded:
                if not self._channels.claim_name(
                    org_id, clean.casefold(), channel_id, now
                ):
                    raise ChannelNameTakenError(
                        "A channel with that name exists."
                    )
                release = row.name_folded
                row.name, row.name_folded = clean, clean.casefold()
        if topic is not None:
            row.topic = topic.strip()[:CHANNEL_TOPIC_MAX]
        if kind is not None:
            row.kind = kind
        if post_policy is not None:
            row.post_policy = post_policy
        if visibility is not None:
            row.visibility = visibility
        if archived is not None:
            self._set_archived(row, org, actor_id, archived, now)
        self._channels.update_channel(row)
        if release is not None:
            self._channels.release_name(org_id, release)
        self._fan("channel.updated", channel_id, org_id)
        self._access.record(
            org_id, actor_id, "channel.update", "chat",
            channel_id, "allowed",
        )
        return self._snap(row)

    def _set_archived(
        self,
        row,
        org: Organization,
        actor_id: UUID,
        archived: bool,
        now: datetime,
    ) -> None:
        if archived and row.archived_at is None:
            row.archived_at, row.archived_by = now, actor_id
            self._channels.release_name(org.id, row.name_folded)
        elif not archived and row.archived_at is not None:
            if not self._channels.claim_name(
                org.id, row.name_folded, row.channel_id, now
            ):
                raise ChannelNameTakenError(
                    "A channel with that name exists."
                )
            row.archived_at = row.archived_by = None

    def list_channel_members(
        self, org_id: UUID, channel_id: UUID, viewer_id: UUID
    ) -> list[ChannelMemberSnapshot]:
        """Roster of one restricted channel (managers and seated members)."""
        org = live_org(self._orgs, org_id)
        row = self._get(org_id, channel_id)
        seated = self._channels.get_channel_member(
            channel_id, viewer_id
        ) is not None
        if row.visibility == "restricted" and not (
            self._manager(org, viewer_id) or seated
        ):
            raise ForbiddenError("Only channel members can do this.")
        if org.owner_id != viewer_id and not is_active_member(
            self._members, org.id, viewer_id
        ):
            raise ForbiddenError("Only org members can do this.")
        out = []
        for seat in self._channels.list_channel_members(channel_id):
            brief = self._users.get_brief(seat.user_id)
            out.append(
                ChannelMemberSnapshot(
                    user_id=seat.user_id,
                    full_name=brief.full_name if brief else "Unknown user",
                    added_at=utc_aware(seat.added_at),
                    avatar_url=self._avatar_url(
                        getattr(brief, "avatar_media_id", None)
                    ),
                )
            )
        return out

    def add_channel_member(
        self, org_id: UUID, channel_id: UUID, actor_id: UUID, user_id: UUID
    ) -> ChannelMemberSnapshot:
        org = live_org(self._orgs, org_id)
        self._require_manager(org, actor_id)
        row = self._get(org_id, channel_id)
        if row.visibility != "restricted":
            raise InvalidChannelStateError(
                "Seats only apply to restricted channels."
            )
        if row.archived_at is not None:
            raise ChannelArchivedError("This channel is archived.")
        if user_id != org.owner_id and not is_active_member(
            self._members, org.id, user_id
        ):
            raise MemberNotFoundError(
                "Channel seats require active org members."
            )
        now = utcnow()
        self._channels.add_channel_member(
            channel_id, org_id, user_id, actor_id, now
        )
        brief = self._users.get_brief(user_id)
        self._access.record(
            org_id, actor_id, "channel.member_add", "chat",
            user_id, "allowed",
        )
        return ChannelMemberSnapshot(
            user_id=user_id,
            full_name=brief.full_name if brief else "Unknown user",
            added_at=now,
            avatar_url=self._avatar_url(
                getattr(brief, "avatar_media_id", None)
            ),
        )

    def remove_channel_member(
        self, org_id: UUID, channel_id: UUID, actor_id: UUID, user_id: UUID
    ) -> None:
        org = live_org(self._orgs, org_id)
        self._require_manager(org, actor_id)
        row = self._get(org_id, channel_id)
        if row.visibility != "restricted":
            raise InvalidChannelStateError(
                "Seats only apply to restricted channels."
            )
        if (
            self._channels.get_channel_member(channel_id, user_id)
            is None
        ):
            raise NotFoundError("Channel member not found.")
        self._channels.remove_channel_member(channel_id, user_id)
        self._access.record(
            org_id, actor_id, "channel.member_remove", "chat",
            user_id, "allowed",
        )
