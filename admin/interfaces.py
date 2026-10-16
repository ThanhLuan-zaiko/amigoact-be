"""Abstract ports for the platform-admin bounded context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from admin.model import MediaModeration


class PlatformRoleStore(ABC):
    """Persistence port for the dual platform-role tables."""

    @abstractmethod
    def grant(
        self,
        user_id: UUID,
        role_id: UUID,
        granted_by: UUID,
        now: datetime,
    ) -> None:
        """Write both directions of a platform role assignment."""

    @abstractmethod
    def revoke(self, user_id: UUID, role_id: UUID) -> None:
        """Remove both directions of a platform role assignment."""

    @abstractmethod
    def has_role(self, user_id: UUID, role_id: UUID) -> bool:
        """Check one user still holds one platform role (unexpired)."""

    @abstractmethod
    def list_holders(self, role_id: UUID) -> list[UUID]:
        """Every user id currently holding one platform role."""


class ModerationStore(ABC):
    """Persistence port for media_moderation buckets."""

    @abstractmethod
    def enqueue(
        self,
        moderation_id: UUID,
        asset_id: UUID,
        now: datetime,
    ) -> MediaModeration:
        """Insert a pending row."""

    @abstractmethod
    def list_by_status(
        self, status: str, limit: int = 50
    ) -> list[MediaModeration]:
        """Newest rows of one status bucket."""

    @abstractmethod
    def mark(
        self,
        from_status: str,
        created_at: datetime,
        moderation_id: UUID,
        to_status: str,
        reviewed_by: UUID,
        note: str | None,
        now: datetime,
    ) -> MediaModeration | None:
        """Move one row into another status bucket."""
