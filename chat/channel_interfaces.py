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
        parent_room_id: UUID | None = None,
        activity_id: UUID | None = None,
    ) -> OrgChatChannelById | None:
        """Claim the casefolded name (LWT) then write the channel rows.

        The claim scope is the parent room for sub-threads (their names
        are unique per parent) or the org for top-level channels; a
        thread row additionally mirrors into org_chat_room_threads.
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
    def list_room_threads(
        self, parent_room_id: UUID
    ) -> list[OrgChatChannelById]:
        """One room's sub-threads, creation order (uuid7 clustering)."""

    @abstractmethod
    def update_channel(self, channel: OrgChatChannelById) -> None:
        """Overwrite the channel rows with the (mutated) snapshot."""

    @abstractmethod
    def claim_name(
        self,
        scope_id: UUID,
        name_folded: str,
        channel_id: UUID,
        now: datetime,
    ) -> bool:
        """LWT-claim one name inside a scope; False while held live.

        scope_id is the org for top-level channels and the parent room
        for sub-threads. A claim owned by a deleted or archived channel
        is stale: it is released and claimed again inside this call.
        """

    @abstractmethod
    def release_name(self, scope_id: UUID, name_folded: str) -> None:
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


