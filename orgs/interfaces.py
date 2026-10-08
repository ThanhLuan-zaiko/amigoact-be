"""Abstract ports for the orgs bounded context (DIP wiring)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from orgs.model import MediaAsset, Organization


class OrgRepository(ABC):
    """Persistence port for orgs plus slug uniqueness and memberships."""

    @abstractmethod
    def create(
        self,
        org_id: UUID,
        owner_id: UUID,
        name: str,
        slug: str,
        description: str,
        kind: str,
        tax_code: str | None,
        legal_rep_name: str | None,
        legal_rep_id: str | None,
        legal_rep_position: str | None,
        legal_status: str,
        now: datetime,
    ) -> Organization:
        """Claim the slug with LWT, then insert org plus owner membership."""

    @abstractmethod
    def get_by_id(self, org_id: UUID) -> Organization | None:
        """Load an org by primary key."""

    @abstractmethod
    def get_by_slug(self, slug: str) -> Organization | None:
        """Load an org through the slug index."""

    @abstractmethod
    def list_by_user(self, user_id: UUID) -> list[Organization]:
        """List every org a user belongs to via the member index."""

    @abstractmethod
    def count_members(self, org_id: UUID) -> int:
        """Count active membership rows for one org."""

    @abstractmethod
    def is_member(self, org_id: UUID, user_id: UUID) -> bool:
        """Single-row membership check for upload and gallery reads."""

    @abstractmethod
    def update_details(
        self, org_id: UUID, name: str, description: str, now: datetime
    ) -> Organization | None:
        """Replace name and description, return the fresh row or None."""

    @abstractmethod
    def mark_deleted(self, org_id: UUID, now: datetime) -> Organization | None:
        """Soft delete: stamp deleted_at, keep every row for restore."""

    @abstractmethod
    def mark_restored(self, org_id: UUID, now: datetime) -> Organization | None:
        """Clear deleted_at so a soft-deleted org becomes visible again."""

    @abstractmethod
    def delete_everything(self, org_id: UUID) -> bool:
        """Hard delete: drop org, slug index, memberships and media rows."""


class MediaRepository(ABC):
    """Persistence port for org gallery metadata (bytes live in MediaStore)."""

    @abstractmethod
    def create_asset(
        self,
        asset_id: UUID,
        org_id: UUID,
        file_url: str,
        mime: str,
        size_bytes: int,
        now: datetime,
    ) -> MediaAsset:
        """Insert the metadata row plus the owner feed row."""

    @abstractmethod
    def list_by_org(self, org_id: UUID) -> list[MediaAsset]:
        """Newest-first gallery rows for one org."""

    @abstractmethod
    def get_asset(self, asset_id: UUID) -> MediaAsset | None:
        """Load one asset by primary key."""

    @abstractmethod
    def delete_asset(self, asset_id: UUID) -> MediaAsset | None:
        """Remove metadata rows, return the removed row for file cleanup."""

    @abstractmethod
    def known_org_ids(self) -> set[str]:
        """Every org id owning a folder, used for orphan sweeps."""
