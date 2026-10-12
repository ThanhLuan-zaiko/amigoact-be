"""Abstract ports for the chat bounded context (DIP wiring)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from chat.model import OrgDmPair, OrgDmRoom, OrgRoomMessage, OrgRoomRead


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
    ) -> OrgRoomMessage:
        """Append one message to its room+month partition."""

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


class ActivityLookup(ABC):
    """Read port: activity rows double as activity-room identities.

    Satisfied by ``ActivityStore.get``; kept as its own port so the chat
    service only depends on the single lookup it needs (ISP).
    """

    @abstractmethod
    def get(self, activity_id: UUID):  # noqa: ANN001, ANN202
        """Activity row exposing org_id and created_at, or None."""


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
