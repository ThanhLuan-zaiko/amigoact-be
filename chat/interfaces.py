"""Abstract ports for the chat bounded context (DIP wiring)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from chat.model import (
    OrgChatChannelById,
    OrgChatChannelMember,
    OrgChatChannelMembership,
    OrgChatChannelName,
    OrgDmPair,
    OrgDmRoom,
    OrgRoomMessage,
    OrgRoomMute,
    OrgRoomPin,
    OrgRoomReaction,
    OrgRoomRead,
)


class ChatStore(ABC):
    """Persistence port for messages plus per-room read pointers."""

    @abstractmethod
    def create(
        self,
        room_id: UUID,
        bucket: str,
        message_id: UUID,
        author_id: UUID,
        body: str,
        now: datetime,
        reply_to_id: UUID | None = None,
        reply_to_author: str | None = None,
        reply_to_body: str | None = None,
        attachments_json: str | None = None,
        mentions_json: str | None = None,
    ) -> OrgRoomMessage:
        """Append one message to its room+month partition."""

    @abstractmethod
    def update(
        self,
        message: OrgRoomMessage,
        body: str,
        now: datetime,
        mentions_json: str | None = None,
    ) -> None:
        """Rewrite the body and stamp edited_at on one row."""

    @abstractmethod
    def get(
        self, room_id: UUID, bucket: str, message_id: UUID
    ) -> OrgRoomMessage | None:
        """Load one message (bucket derives from the UUIDv7 timestamp)."""

    @abstractmethod
    def list_before(
        self, room_id: UUID, bucket: str, upper: UUID | None, limit: int
    ) -> list[OrgRoomMessage]:
        """Newest-first slice under `upper` inside one bucket."""

    @abstractmethod
    def count_after(
        self, room_id: UUID, bucket: str, lower: UUID | None
    ) -> int:
        """Rows newer than `lower` inside one bucket (unread math)."""

    @abstractmethod
    def delete(self, message: OrgRoomMessage) -> None:
        """Drop one message row."""

    @abstractmethod
    def get_read(self, room_id: UUID, user_id: UUID) -> OrgRoomRead | None:
        """Load the member's read pointer, or None when never marked."""

    @abstractmethod
    def mark_read(
        self,
        room_id: UUID,
        user_id: UUID,
        message_id: UUID,
        now: datetime,
    ) -> None:
        """Upsert the member's read pointer."""

    @abstractmethod
    def get_dm_room(self, user_id: UUID, room_id: UUID) -> OrgDmRoom | None:
        """Participant row proving the user may open this dm room."""

    @abstractmethod
    def list_dm_rooms(self, user_id: UUID) -> list[OrgDmRoom]:
        """Every dm inbox row of the user across orgs."""

    @abstractmethod
    def find_dm_pair(
        self, org_id: UUID, user_lo: UUID, user_hi: UUID
    ) -> OrgDmPair | None:
        """Existing canonical pair row, or None when never opened."""

    @abstractmethod
    def set_reaction(
        self,
        room_id: UUID,
        message_id: UUID,
        user_id: UUID,
        emoji: str,
        now: datetime,
    ) -> bool:
        """Toggle one (emoji, user) reaction; True when it was added."""

    @abstractmethod
    def list_reactions(
        self, room_id: UUID, message_id: UUID
    ) -> list[OrgRoomReaction]:
        """Every reaction row of one message partition."""

    @abstractmethod
    def set_pin(
        self,
        room_id: UUID,
        message_id: UUID,
        pinned_by: UUID,
        now: datetime,
    ) -> None:
        """Replace the room's pinned slot (one pin per room)."""

    @abstractmethod
    def clear_pin(self, room_id: UUID) -> None:
        """Drop the pinned slot."""

    @abstractmethod
    def get_pin(self, room_id: UUID) -> OrgRoomPin | None:
        """Current pinned row or None."""

    @abstractmethod
    def set_mute(self, user_id: UUID, room_id: UUID, now: datetime) -> None:
        """Mute one room for the user."""

    @abstractmethod
    def clear_mute(self, user_id: UUID, room_id: UUID) -> None:
        """Unmute one room."""

    @abstractmethod
    def list_mutes(self, user_id: UUID) -> list[OrgRoomMute]:
        """Every muted room of the user (inbox joins on it)."""

    @abstractmethod
    def create_dm_room(
        self,
        room_id: UUID,
        org_id: UUID,
        user_lo: UUID,
        user_hi: UUID,
        now: datetime,
    ) -> OrgDmPair:
        """Claim the pair row (LWT) and link both participant inboxes.

        On a creation race the winner's pair row is returned so both
        callers converge on one room id.
        """


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


class ActivityLookup(ABC):
    """Read port: activity rows double as activity-room identities.

    Satisfied by ``ActivityStore``; kept as its own port so the chat
    service only depends on the lookups it needs (ISP).
    """

    @abstractmethod
    def get(self, activity_id: UUID):  # noqa: ANN001, ANN202
        """Activity row exposing org_id and created_at, or None."""

    @abstractmethod
    def list_by_org(self, org_id: UUID, limit: int = 50):  # noqa: ANN001, ANN202
        """Activity rows of one org (inbox room enumeration)."""


class ChatEvents(ABC):
    """Realtime fan-out port for room changes (best-effort)."""

    @abstractmethod
    def message_changed(
        self,
        room_id: UUID,
        action: str,
        message_id: UUID,
        actor_id: UUID,
    ) -> None:
        """Broadcast to chat:{room_id} subscribers."""

    @abstractmethod
    def inbox_changed(
        self,
        action: str,
        room_id: UUID,
        org_id: UUID,
        peer_ids: tuple[UUID, ...] = (),
    ) -> None:
        """Inbox-scope hint carrying ``scope: "chat-inbox"``.

        Group rooms (general/activity) publish once to members:{org_id}
        so every subscribed member refreshes their inbox; dm rooms
        publish to notifications:{user_id} of each participant instead,
        keeping the room's existence off the shared org channel.
        """
