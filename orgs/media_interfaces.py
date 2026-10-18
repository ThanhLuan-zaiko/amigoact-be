"""Media persistence port (split from interfaces.py for the line cap)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from orgs.model import MediaAsset


class MediaRepository(ABC):
    """Persistence port for org gallery metadata (bytes live in MediaStore)."""

    @abstractmethod
    def create_asset(
        self,
        asset_id: UUID,
        owner_id: UUID,
        file_url: str,
        mime: str,
        size_bytes: int,
        now: datetime,
        role: str = "gallery",
        file_hash: str | None = None,
        uploader_id: UUID | None = None,
        original_name: str | None = None,
        *,
        owner_type: str,
        owner_feed: bool = True,
    ) -> MediaAsset:
        """Insert metadata plus uploader/hash feeds; owner_feed=False skips media_by_owner.

        `owner_type` is required: every asset must explicitly declare
        which bounded context owns it (org gallery, chat room, post,
        activity, certificate, user avatar).
        """

    @abstractmethod
    def list_gallery(self, org_id: UUID) -> list[MediaAsset]:
        """Newest-first gallery rows for one org.

        Implementations MUST exclude every non-gallery owner type and
        role at this layer: callers must not be able to retrieve chat,
        post, activity, certificate, or avatar rows through this port.
        """

    @abstractmethod
    def get_asset(self, asset_id: UUID) -> MediaAsset | None:
        """Load one asset by primary key."""

    @abstractmethod
    def set_role(self, asset_id: UUID, role: str) -> MediaAsset | None:
        """Update the gallery/cover/logo role, return the fresh row."""

    @abstractmethod
    def replace_content(
        self,
        asset_id: UUID,
        file_url: str,
        mime: str,
        size_bytes: int,
        file_hash: str | None,
        original_name: str | None,
        now: datetime,
    ) -> MediaAsset | None:
        """Swap stored file metadata after a byte rewrite; feeds stay in sync."""

    @abstractmethod
    def delete_asset(self, asset_id: UUID) -> MediaAsset | None:
        """Remove metadata rows, return the removed row for file cleanup."""

    @abstractmethod
    def set_upload_status(self, asset_id: UUID, status: str) -> None:
        """Flip active/rejected visibility after moderation review."""

    @abstractmethod
    def protected_dir_ids(self) -> set[str]:
        """Folder names under media/orgs/ that must survive orphan sweeps.

        Live org ids plus every owner_id a live asset points at: legacy
        activity folders are named by the activity id, and an asset row
        is the only durable proof such a folder is wanted.
        """
