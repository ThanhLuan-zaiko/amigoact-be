"""Port for chat safety state: attachment policy and member timeouts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class TimeoutRecord:
    """One active (or just-expired) chat timeout."""

    user_id: UUID
    until: datetime
    set_by: UUID
    reason: str = ""


class ChatSafetyStore(ABC):
    @abstractmethod
    def attach_restricted(self, org_id: UUID) -> bool:
        """True when attaching files needs chat:attach in this org."""

    @abstractmethod
    def set_attach_restricted(self, org_id: UUID, restricted: bool) -> None:
        """Turn the attachment restriction on or off."""

    @abstractmethod
    def get_timeout(self, org_id: UUID, user_id: UUID) -> TimeoutRecord | None:
        """The member's timeout row, if one is stored."""

    @abstractmethod
    def put_timeout(
        self,
        org_id: UUID,
        record: TimeoutRecord,
        ttl_seconds: int,
    ) -> None:
        """Store or extend a timeout; the row expires after ttl_seconds."""

    @abstractmethod
    def delete_timeout(self, org_id: UUID, user_id: UUID) -> None:
        """Lift a timeout early (idempotent)."""

    @abstractmethod
    def list_timeouts(self, org_id: UUID) -> list[TimeoutRecord]:
        """Every stored timeout of the org; callers drop expired ones."""
