"""ChannelStore port split from interfaces.py for the 350-line rule.

A channel_id doubles as the room id in org_room_messages, so this port
only owns channel metadata; message storage stays ChatStore.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from chat.model import (
    OrgChatChannelById,
    OrgChatChannelMember,
    OrgChatChannelMembership,
)


class ChannelStore(ABC):
    """Persistence port for named org channels and restricted rosters.

    channel_id doubles as the room id in org_room_messages, so this
    port only owns channel metadata; message storage stays ChatStore.
    """

    @abstractmethod
    def create_channel(
        self,
        org_id: UUID,
        name: str,
        topic: str,
        kind: str,
        post_policy: str,
        visibility: str,
        created_by: UUID,
        now: datetime,
    ) -> OrgChatChannelById | None:
        """Claim the casefolded name (LWT) then write both channel rows.

        Returns None when the name is already held by another live
        channel; callers map that to CHANNEL_NAME_TAKEN.
        """

    @abstractmethod
    def get_channel(self, channel_id: UUID) -> OrgChatChannelById | None:
        """Row mirror by channel id (room-resolution lookup)."""

    @abstractmethod
    def get_channel_in_org(
        self, org_id: UUID, channel_id: UUID
    ) -> OrgChatChannelById | None:
        """Row mirror scoped to one org (channel-management lookups)."""

    @abstractmethod
    def list_channels(self, org_id: UUID) -> list[OrgChatChannelById]:
        """Every channel row of one org, creation order (uuid7)."""

    @abstractmethod
    def update_channel(self, channel: OrgChatChannelById) -> None:
        """Overwrite both channel rows with the (mutated) snapshot."""

    @abstractmethod
    def claim_name(
        self,
        org_id: UUID,
        name_folded: str,
        channel_id: UUID,
        now: datetime,
    ) -> bool:
        """LWT-claim one channel name; False while a live channel holds it.

        A claim owned by a deleted or archived channel is stale: it is
        released and claimed again inside this call.
        """

    @abstractmethod
    def release_name(self, org_id: UUID, name_folded: str) -> None:
        """Drop a name claim (rename/archive frees it for reuse)."""

    @abstractmethod
    def add_channel_member(
        self,
        channel_id: UUID,
        org_id: UUID,
        user_id: UUID,
        added_by: UUID,
        now: datetime,
    ) -> None:
        """Grant a restricted-channel seat (both roster tables)."""

    @abstractmethod
    def remove_channel_member(
        self, channel_id: UUID, user_id: UUID
    ) -> None:
        """Revoke a restricted-channel seat (both roster tables)."""

    @abstractmethod
    def get_channel_member(
        self, channel_id: UUID, user_id: UUID
    ) -> OrgChatChannelMember | None:
        """One roster seat, or None (restricted-room ACL check)."""

    @abstractmethod
    def list_channel_members(
        self, channel_id: UUID
    ) -> list[OrgChatChannelMember]:
        """Full roster of one restricted channel."""

    @abstractmethod
    def list_channel_memberships(
        self, user_id: UUID
    ) -> list[OrgChatChannelMembership]:
        """Every restricted-channel seat of the user (inbox filter)."""


