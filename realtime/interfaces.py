"""Abstract ports for the realtime bounded context (DIP wiring)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from realtime.model import WsTicket


class WsTicketStore(ABC):
    """Persistence port for one-time WebSocket handshake tickets."""

    @abstractmethod
    def create(
        self,
        ticket_hash: str,
        user_id: UUID,
        expires_at: datetime,
        now: datetime,
    ) -> None:
        """Persist a hashed ticket row bound to one user."""

    @abstractmethod
    def consume(self, ticket_hash: str) -> WsTicket | None:
        """Atomically take a ticket (single use) or return None."""


class OrgMembership(ABC):
    """Read port: is one user a member of one organization."""

    @abstractmethod
    def is_member(self, org_id: UUID, user_id: UUID) -> bool:
        """True when the user holds an active membership row."""


class AttendanceAccess(ABC):
    """Read port: may the user watch an activity check-in feed."""

    @abstractmethod
    def can_view(self, activity_id: UUID, user_id: UUID) -> bool:
        """True for staff of the org owning the activity."""


class ChatRoomAccess(ABC):
    """Read port: may the user subscribe to one chat:{room_id} channel.

    Implemented by the chat service itself so subscription checks share
    the exact room-resolution rules (general / activity / dm) instead of
    duplicating them behind the transport.
    """

    @abstractmethod
    def can_access(self, room_id: UUID, user_id: UUID) -> bool:
        """True when the room resolves for this user and they are a member."""


class UserLookup(ABC):
    """Read port: account status gate for socket admission.

    The router cannot see the auth tables without leaking DIP, so the
    post-ticket status check goes through this port (
    a suspended or deleted account must never hold a socket open).
    """

    @abstractmethod
    def is_active(self, user_id: UUID) -> bool:
        """True only when the user exists and their status is active."""

    @abstractmethod
    def set_last_seen(self, user_id: UUID, now: datetime) -> None:
        """User-level last-seen stamp on presence transitions."""


class PresenceDirectory(ABC):
    """Read port: org rosters for presence fan-out and snapshots.

    Presence is org-scoped: transitions publish to every org the user
    belongs to, and subscribing to members:{org} yields the online ids
    of that roster only. Only active memberships count for either side.
    """

    @abstractmethod
    def orgs_of(self, user_id: UUID) -> list[UUID]:
        """Org ids where the user holds an active membership."""

    @abstractmethod
    def member_ids_of(self, org_id: UUID) -> list[UUID]:
        """User ids holding an active membership in one org."""
