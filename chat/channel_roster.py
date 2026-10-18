"""Restricted-channel roster management (seats) - split from
channel_service.py for the 350-line rule.

Seats only exist on top-level restricted channels: sub-threads inherit
the parent channel's audience, so roster calls on a thread row are
rejected here and the parent channel is managed instead.
"""

from __future__ import annotations

from uuid import UUID

from chat.channel_helpers import (
    can_open_channel,
    channel_row_or_404,
    require_channel_manager,
    require_org_member,
)
from chat.channel_interfaces import ChannelStore
from chat.dtos import ChannelMemberSnapshot
from core.exceptions import (
    ChannelArchivedError,
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
from rbac.interfaces import AccessControl


class ChannelRosterService:
    """Restricted-channel seat listing/granting (managers only)."""

    def __init__(
        self,
        channels: ChannelStore,
        orgs: OrgRepository,
        members: MemberRepository,
        users: UserDirectory,
        access: AccessControl,
        media: MediaRepository | None = None,
    ) -> None:
        self._channels = channels
        self._orgs = orgs
        self._members = members
        self._users = users
        self._access = access
        self._media = media

    def _avatar_url(self, asset_id: UUID | None) -> str | None:
        if asset_id is None or self._media is None:
            return None
        asset = self._media.get_asset(asset_id)
        return f"/media/{asset.file_url}" if asset is not None else None

    def _member_snap(
        self, user_id: UUID, added_at
    ) -> ChannelMemberSnapshot:  # noqa: ANN001
        brief = self._users.get_brief(user_id)
        return ChannelMemberSnapshot(
            user_id=user_id,
            full_name=brief.full_name if brief else "Unknown user",
            added_at=utc_aware(added_at),
            avatar_url=self._avatar_url(
                getattr(brief, "avatar_media_id", None)
            ),
        )

    def _restricted_row(self, org_id: UUID, channel_id: UUID):  # noqa: ANN202
        row = channel_row_or_404(self._channels, org_id, channel_id)
        if getattr(row, "parent_room_id", None) is not None:
            raise InvalidChannelStateError(
                "Threads inherit the parent channel's roster."
            )
        if row.visibility != "restricted":
            raise InvalidChannelStateError(
                "Seats only apply to restricted channels."
            )
        return row

    def list_channel_members(
        self, org_id: UUID, channel_id: UUID, viewer_id: UUID
    ) -> list[ChannelMemberSnapshot]:
        """Roster of one restricted channel (managers and seated members)."""
        org = live_org(self._orgs, org_id)
        row = channel_row_or_404(self._channels, org_id, channel_id)
        if row.visibility == "restricted" and not can_open_channel(
            self._access, self._channels, org, row, viewer_id
        ):
            raise ForbiddenError("Only channel members can do this.")
        require_org_member(self._members, org, viewer_id)
        return [
            self._member_snap(seat.user_id, seat.added_at)
            for seat in self._channels.list_channel_members(channel_id)
        ]

    def add_channel_member(
        self, org_id: UUID, channel_id: UUID, actor_id: UUID, user_id: UUID
    ) -> ChannelMemberSnapshot:
        org = live_org(self._orgs, org_id)
        require_channel_manager(self._access, org, actor_id)
        row = self._restricted_row(org_id, channel_id)
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
        self._access.record(
            org_id, actor_id, "channel.member_add", "chat",
            user_id, "allowed",
        )
        return self._member_snap(user_id, now)

    def remove_channel_member(
        self, org_id: UUID, channel_id: UUID, actor_id: UUID, user_id: UUID
    ) -> None:
        org = live_org(self._orgs, org_id)
        require_channel_manager(self._access, org, actor_id)
        self._restricted_row(org_id, channel_id)
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
