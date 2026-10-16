"""Persistence port for API keys."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from apikeys.model import ApiKey, ApiKeyByOrg


class ApiKeyStore(ABC):
    """Store keyed by digest, mirrored per-org for listings."""

    @abstractmethod
    def create(
        self,
        key_hash: str,
        key_id: UUID,
        org_id: UUID,
        name: str,
        scopes: set[str],
        expires_at: datetime | None,
        now: datetime,
    ) -> ApiKey:
        """Insert into both api_keys and api_keys_by_org."""

    @abstractmethod
    def get_by_hash(self, key_hash: str) -> ApiKey | None:
        """Resolve a presented key to its stored row."""

    @abstractmethod
    def list_for_org(self, org_id: UUID) -> list[ApiKeyByOrg]:
        """Every key row owned by the org."""

    @abstractmethod
    def revoke(self, org_id: UUID, key_id: UUID, now: datetime) -> None:
        """Mark revoked in both tables."""

    @abstractmethod
    def touch(self, key_hash: str, org_id: UUID, key_id: UUID, now: datetime) -> None:
        """Update last_used_at on successful authentication."""
