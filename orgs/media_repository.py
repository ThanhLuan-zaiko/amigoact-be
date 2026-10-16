"""cqlengine persistence for org media assets and their feed tables."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from core.security import utcnow
from orgs.interfaces import MediaRepository
from orgs.model import (
    MediaAsset,
    MediaByHash,
    MediaByOwner,
    MediaByUploader,
    Organization,
)


def media_feeds_delete(row: MediaAsset) -> None:
    """Drop the hash/uploader index rows that point at a media asset."""
    if getattr(row, "file_hash", None):
        MediaByHash.objects(file_hash=row.file_hash).delete()
    uploader = getattr(row, "uploader_id", None)
    if uploader is not None and row.created_at is not None:
        MediaByUploader.objects(
            uploader_id=uploader,
            created_at=row.created_at,
            asset_id=row.asset_id,
        ).delete()


class CqlMediaRepository(MediaRepository):
    """Gallery metadata mirrored into the per-owner feed table."""

    def create_asset(
        self,
        asset_id: UUID,
        org_id: UUID,
        file_url: str,
        mime: str,
        size_bytes: int,
        now: datetime,
        role: str = "gallery",
        file_hash: str | None = None,
        uploader_id: UUID | None = None,
        original_name: str | None = None,
        owner_type: str = "organization",
    ) -> MediaAsset:
        row = MediaAsset.create(
            asset_id=asset_id,
            owner_id=org_id,
            owner_type=owner_type,
            file_url=file_url,
            file_hash=file_hash,
            mime=mime,
            size_bytes=size_bytes,
            role=role,
            uploader_id=uploader_id,
            storage_key=file_url,
            backend="local",
            original_name=original_name,
            visibility="organization",
            upload_status="active",
            created_at=now,
            updated_at=now,
        )
        MediaByOwner.create(
            owner_id=org_id,
            created_at=now,
            asset_id=asset_id,
            file_url=file_url,
            mime=mime,
            owner_type=owner_type,
        )
        if file_hash:
            MediaByHash.create(file_hash=file_hash, asset_id=asset_id)
        if uploader_id is not None:
            MediaByUploader.create(
                uploader_id=uploader_id,
                created_at=now,
                asset_id=asset_id,
                file_url=file_url,
                mime=mime,
                owner_type="organization",
            )
        return row

    def list_by_org(self, org_id: UUID) -> list[MediaAsset]:
        rows: list[MediaAsset] = []
        for link in MediaByOwner.objects(owner_id=org_id).all():
            asset = self.get_asset(link.asset_id)
            if asset is not None:
                rows.append(asset)
        return rows

    def get_asset(self, asset_id: UUID) -> MediaAsset | None:
        return MediaAsset.objects(asset_id=asset_id).first()

    def set_role(self, asset_id: UUID, role: str) -> MediaAsset | None:
        if self.get_asset(asset_id) is None:
            return None
        MediaAsset.objects(asset_id=asset_id).update(
            role=role, updated_at=utcnow()
        )
        return self.get_asset(asset_id)

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
        row = self.get_asset(asset_id)
        if row is None:
            return None
        old_hash = getattr(row, "file_hash", None)
        MediaAsset.objects(asset_id=asset_id).update(
            file_url=file_url,
            storage_key=file_url,
            mime=mime,
            size_bytes=size_bytes,
            file_hash=file_hash,
            original_name=original_name,
            updated_at=now,
        )
        # Denormalized feeds keep file_url/mime for fan-out rendering.
        MediaByOwner.objects(
            owner_id=row.owner_id, created_at=row.created_at, asset_id=asset_id
        ).update(file_url=file_url, mime=mime)
        if row.uploader_id is not None:
            MediaByUploader.objects(
                uploader_id=row.uploader_id,
                created_at=row.created_at,
                asset_id=asset_id,
            ).update(file_url=file_url, mime=mime)
        # Hash index is keyed by content: re-point it at this asset.
        # Two assets with identical bytes share one row; last writer wins.
        if old_hash != file_hash:
            if old_hash:
                MediaByHash.objects(file_hash=old_hash).delete()
            if file_hash:
                MediaByHash.create(file_hash=file_hash, asset_id=asset_id)
        return self.get_asset(asset_id)

    def delete_asset(self, asset_id: UUID) -> MediaAsset | None:
        row = self.get_asset(asset_id)
        if row is None:
            return None
        for link in MediaByOwner.objects(owner_id=row.owner_id).all():
            if link.asset_id == asset_id:
                link.delete()
        media_feeds_delete(row)
        row.delete()
        return row

    def set_upload_status(self, asset_id: UUID, status: str) -> None:
        MediaAsset.objects(asset_id=asset_id).update(upload_status=status)

    def known_org_ids(self) -> set[str]:
        return {str(org.id) for org in Organization.objects.all()}
