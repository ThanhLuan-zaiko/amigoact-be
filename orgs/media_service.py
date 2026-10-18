"""Org gallery business rules: upload, roles, delete. No FastAPI."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from core.exceptions import (
    ForbiddenError,
    InvalidBusinessProfileError,
    InvalidMediaRoleError,
    MediaTooLargeError,
    NotFoundError,
    OrgDeletedError,
    UnsupportedMediaError,
)
from core.media import MediaStore, media_kind, normalize_image
from core.media_rules import (
    BRAND_ROLES,
    GALLERY_ROLES,
    asset_role,
    is_gallery_asset,
    prepare_upload,
)
from core.security import utcnow
from orgs.interfaces import (
    MediaRepository,
    OrgDirectoryEvents,
    OrgRepository,
)
from rbac.interfaces import AccessControl

if TYPE_CHECKING:
    from admin.interfaces import ModerationStore
    from orgs.model import MediaAsset, Organization


@dataclass(frozen=True)
class MediaSnapshot:
    """One stored gallery file with its public URL."""

    id: UUID
    org_id: UUID
    kind: str
    role: str
    mime: str
    size_bytes: int
    file_url: str
    uploader_id: UUID | None
    original_name: str | None
    upload_status: str
    created_at: datetime
    updated_at: datetime | None


class MediaService:
    """Gallery lifecycle: member uploads, owner/media manager brands."""

    def __init__(
        self,
        orgs: OrgRepository,
        media: MediaRepository,
        store: MediaStore,
        max_image_bytes: int = 10 * 1024 * 1024,
        max_video_bytes: int = 100 * 1024 * 1024,
        access: AccessControl | None = None,
        events: OrgDirectoryEvents | None = None,
        moderation: "ModerationStore | None" = None,
    ) -> None:
        self._orgs = orgs
        self._media = media
        self._store = store
        self._max_image_bytes = max_image_bytes
        self._max_video_bytes = max_video_bytes
        self._access = access
        self._events = events
        self._moderation = moderation

    def _emit_updated(self, org: Organization) -> None:
        """Ping the public directory on every gallery change."""
        if self._events is not None:
            self._events.directory_changed("updated", org.id, org.slug)

    def _owned(self, org_id: UUID) -> Organization:
        """Load an org or 404."""
        org = self._orgs.get_by_id(org_id)
        if org is None:
            raise NotFoundError("Organization not found.")
        return org

    def _require_live(self, org_id: UUID, user_id: UUID) -> Organization:
        org = self._owned(org_id)
        if org.owner_id != user_id:
            raise ForbiddenError("Only the org owner can do this.")
        if getattr(org, "deleted_at", None) is not None:
            raise OrgDeletedError("Organization is soft-deleted.")
        return org

    def _can_manage(self, org: Organization, user_id: UUID) -> bool:
        """Owner, or an active member holding the media:manage permission."""
        if org.owner_id == user_id:
            return True
        return bool(
            self._access is not None
            and self._orgs.is_member(org.id, user_id)
            and self._access.has_permission(org.id, user_id, "media:manage")
        )

    def _require_manager(
        self, org_id: UUID, user_id: UUID
    ) -> Organization:
        org = self._owned(org_id)
        if getattr(org, "deleted_at", None) is not None:
            raise OrgDeletedError("Organization is soft-deleted.")
        if not self._can_manage(org, user_id):
            raise ForbiddenError("Only org media managers can do this.")
        return org

    def _media_snapshot(self, org_id: UUID, row: MediaAsset) -> MediaSnapshot:
        """Map one media row to its public snapshot."""
        return MediaSnapshot(
            id=row.asset_id,
            org_id=org_id,
            kind=media_kind(row.mime) or "image",
            role=asset_role(row),
            mime=row.mime,
            size_bytes=int(row.size_bytes or 0),
            file_url=f"/media/{row.file_url}",
            uploader_id=getattr(row, "uploader_id", None),
            original_name=getattr(row, "original_name", None),
            upload_status=getattr(row, "upload_status", None) or "active",
            created_at=row.created_at,
            updated_at=getattr(row, "updated_at", None),
        )

    def _demote_role(
        self, org_id: UUID, role: str, keep: UUID | None = None
    ) -> None:
        """Single cover/logo per org; last writer wins on concurrent race."""
        # TODO: enforce branding uniqueness with LWT on a dedicated table.
        for other in self._media.list_gallery(org_id):
            if (
                is_gallery_asset(other, org_id)
                and asset_role(other) == role
                and other.asset_id != keep
            ):
                self._media.set_role(other.asset_id, "gallery")

    def _sync_brand(
        self, org_id: UUID, role: str, asset_id: UUID | None
    ) -> None:
        """Point the org's cover_media_id/logo_media_id at the asset."""
        self._orgs.set_brand_media(org_id, role, asset_id, utcnow())

    def _clear_brand_if(self, org_id: UUID, asset_id: UUID) -> None:
        """Drop brand pointers that reference a deleted/demoted asset."""
        org = self._orgs.get_by_id(org_id)
        if org is None:
            return
        if getattr(org, "cover_media_id", None) == asset_id:
            self._sync_brand(org_id, "cover", None)
        if getattr(org, "logo_media_id", None) == asset_id:
            self._sync_brand(org_id, "logo", None)

    def _check_role(
        self, org: Organization, user_id: UUID, kind: str, role: str
    ) -> None:
        """Brand roles (cover/logo) are owner-only and images only."""
        if role not in GALLERY_ROLES:
            raise InvalidMediaRoleError("Media role is invalid.")
        if role in BRAND_ROLES:
            if kind != "image":
                raise InvalidMediaRoleError("Cover and logo must be images.")
            if not self._can_manage(org, user_id):
                raise ForbiddenError(
                    "Only org media managers can mark cover or logo."
                )

    def upload_media(
        self,
        org_id: UUID,
        user_id: UUID,
        filename: str,
        mime: str,
        content: bytes,
        role: str = "gallery",
    ) -> MediaSnapshot:
        """Any member uploads one image/video into the org folder."""
        org = self._owned(org_id)
        if getattr(org, "deleted_at", None) is not None:
            raise OrgDeletedError("Organization is soft-deleted.")
        if not self._orgs.is_member(org_id, user_id):
            raise ForbiddenError("Only org members can upload media.")
        prepared = prepare_upload(
            mime, content, self._max_image_bytes, self._max_video_bytes
        )
        self._check_role(org, user_id, prepared.kind, role)
        from core.ids import uuid7

        asset_id = uuid7()
        relative = self._store.save_typed(
            org_id, asset_id, prepared.mime, filename, prepared.content
        )
        now = utcnow()
        if role in BRAND_ROLES:
            self._demote_role(org_id, role)
        row = self._media.create_asset(
            asset_id,
            org_id,
            relative,
            prepared.mime,
            len(prepared.content),
            now,
            role,
            file_hash=prepared.file_hash,
            uploader_id=user_id,
            original_name=filename,
            owner_type="organization",
        )
        if self._moderation is not None:
            self._moderation.enqueue(uuid7(), asset_id, now)
        if role in BRAND_ROLES:
            self._sync_brand(org_id, role, asset_id)
        self._emit_updated(org)
        return self._media_snapshot(org_id, row)

    def set_media_role(
        self, org_id: UUID, user_id: UUID, media_id: UUID, role: str
    ) -> MediaSnapshot:
        """Owner or media manager marks cover/logo, or clears it."""
        org = self._require_manager(org_id, user_id)
        if role not in GALLERY_ROLES:
            raise InvalidMediaRoleError("Media role is invalid.")
        row = self._media.get_asset(media_id)
        if not is_gallery_asset(row, org_id):
            raise NotFoundError("Media not found.")
        if role in BRAND_ROLES and media_kind(row.mime) != "image":
            raise InvalidMediaRoleError("Cover and logo must be images.")
        if role in BRAND_ROLES:
            self._demote_role(org_id, role, keep=media_id)
        updated = self._media.set_role(media_id, role)
        assert updated is not None
        if role in BRAND_ROLES:
            self._sync_brand(org_id, role, media_id)
        else:
            self._clear_brand_if(org_id, media_id)
        self._emit_updated(org)
        return self._media_snapshot(org_id, updated)

    def list_media(self, org_id: UUID, user_id: UUID) -> list[MediaSnapshot]:
        """Newest-first gallery for members of a live org."""
        org = self._owned(org_id)
        if getattr(org, "deleted_at", None) is not None:
            raise OrgDeletedError("Organization is soft-deleted.")
        if not self._orgs.is_member(org_id, user_id):
            raise ForbiddenError("Only org members can view media.")
        return [
            self._media_snapshot(org_id, row)
            for row in self._media.list_gallery(org_id)
            if is_gallery_asset(row, org_id)
        ]

    def replace_media(
        self,
        org_id: UUID,
        user_id: UUID,
        media_id: UUID,
        filename: str,
        mime: str,
        content: bytes,
    ) -> MediaSnapshot:
        """Owner rewrites an image's bytes in place (re-crop/re-filter).

        Keeps asset_id, role and brand pointers untouched; only the stored
        file plus its metadata change. New file is written before the row
        updates, old file is swept best-effort when the path moves.
        """
        org = self._require_manager(org_id, user_id)
        row = self._media.get_asset(media_id)
        if not is_gallery_asset(row, org_id):
            raise NotFoundError("Media not found.")
        if media_kind(row.mime) != "image":
            raise UnsupportedMediaError("Only image assets can be re-edited.")
        if media_kind(mime) != "image":
            raise UnsupportedMediaError("Only images can replace an image.")
        if len(content) > self._max_image_bytes:
            raise MediaTooLargeError("File exceeds the size limit.")
        try:
            mime, content = normalize_image(content, mime)
        except ValueError as exc:
            raise MediaTooLargeError(
                "Image exceeds the pixel limit."
            ) from exc
        old_relative = row.file_url
        new_relative = self._store.save_typed(
            org_id, media_id, mime, filename, content
        )
        updated = self._media.replace_content(
            media_id,
            new_relative,
            mime,
            len(content),
            hashlib.sha256(content).hexdigest(),
            filename,
            utcnow(),
        )
        assert updated is not None
        if old_relative != new_relative:
            self._store.delete_file(old_relative)
        self._emit_updated(org)
        return self._media_snapshot(org_id, updated)

    def delete_media(self, org_id: UUID, user_id: UUID, media_id: UUID) -> None:
        """Owner or media manager removes one gallery file."""
        org = self._require_manager(org_id, user_id)
        row = self._media.get_asset(media_id)
        if not is_gallery_asset(row, org_id):
            raise NotFoundError("Media not found.")
        self._clear_brand_if(org_id, media_id)
        self._media.delete_asset(media_id)
        self._store.delete_file(row.file_url)
        self._emit_updated(org)

    def delete_all_media(self, org_id: UUID, user_id: UUID) -> int:
        """Owner or media manager wipes the gallery, 500 rows per call."""
        # Idempotent: missing rows/files are skipped, safe to retry.
        org = self._require_manager(org_id, user_id)
        gallery = [
            row
            for row in self._media.list_gallery(org_id)
            if is_gallery_asset(row, org_id)
        ][:500]
        removed = 0
        for row in gallery:
            self._media.delete_asset(row.asset_id)
            self._store.delete_file(row.file_url)
            removed += 1
        self._sync_brand(org_id, "cover", None)
        self._sync_brand(org_id, "logo", None)
        if removed > 0:
            self._emit_updated(org)
        return removed
