"""Abstract ports for the platform-admin bounded context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID


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
