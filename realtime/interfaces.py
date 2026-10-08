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
