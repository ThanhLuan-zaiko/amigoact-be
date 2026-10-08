"""Org business rules. No FastAPI, no CQL strings here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from core.exceptions import (
    ForbiddenError,
    InvalidBusinessProfileError,
    MediaTooLargeError,
    NotFoundError,
    OrgDeletedError,
    UnsupportedMediaError,
)
from core.media import MediaStore, media_kind
from core.security import utcnow
from orgs.interfaces import MediaRepository, OrgRepository
from orgs.repository import generate_org_id

if TYPE_CHECKING:
    from orgs.model import Organization

_ORG_KINDS = ("organization", "club", "group", "business")


@dataclass(frozen=True)
class OrgSnapshot:
    """Created org plus live member count for the response card."""

    id: UUID
    owner_id: UUID
    name: str
    slug: str
    description: str
    kind: str
    tax_code: str | None
    legal_rep_name: str | None
    legal_rep_id: str | None
    legal_rep_position: str | None
    legal_status: str
    status: str
    deleted_at: datetime | None
    member_count: int
    created_at: datetime


@dataclass(frozen=True)
class MediaSnapshot:
    """One stored gallery file with its public URL."""

    id: UUID
    org_id: UUID
    kind: str
    mime: str
    size_bytes: int
    file_url: str
    created_at: datetime


class OrgService:
    """Org CRUD with soft/hard delete plus the org gallery."""

    def __init__(
        self,
        orgs: OrgRepository,
        media: MediaRepository | None = None,
        store: MediaStore | None = None,
        max_image_bytes: int = 10 * 1024 * 1024,
        max_video_bytes: int = 100 * 1024 * 1024,
    ) -> None:
        self._orgs = orgs
        self._media = media
        self._store = store
        self._max_image_bytes = max_image_bytes
        self._max_video_bytes = max_video_bytes

    def _snapshot(self, org_id: UUID) -> OrgSnapshot:
        org = self._orgs.get_by_id(org_id)
        assert org is not None
        return OrgSnapshot(
            id=org.id,
            owner_id=org.owner_id,
            name=org.name,
            slug=org.slug,
            description=org.description or "",
            kind=org.org_type,
            tax_code=org.tax_code,
            legal_rep_name=org.legal_rep_name,
            legal_rep_id=org.legal_rep_id,
            legal_rep_position=org.legal_rep_position,
            legal_status=org.legal_status,
            status=getattr(org, "status", "active") or "active",
            deleted_at=getattr(org, "deleted_at", None),
            member_count=self._orgs.count_members(org.id),
            created_at=org.created_at,
        )

    def _owned(self, org_id: UUID) -> Organization:
        """Load an org or 404."""
        org = self._orgs.get_by_id(org_id)
        if org is None:
            raise NotFoundError("Organization not found.")
        return org

    def _require_owner(self, org_id: UUID, user_id: UUID) -> Organization:
        org = self._owned(org_id)
        if org.owner_id != user_id:
            raise ForbiddenError("Only the org owner can do this.")
        return org

    def _require_live(self, org_id: UUID, user_id: UUID) -> Organization:
        org = self._require_owner(org_id, user_id)
        if getattr(org, "deleted_at", None) is not None:
            raise OrgDeletedError("Organization is soft-deleted.")
        return org

    def create_org(
        self,
        owner_id: UUID,
        name: str,
        slug: str,
        description: str,
        kind: str,
        tax_code: str | None = None,
        legal_rep_name: str | None = None,
        legal_rep_id: str | None = None,
        legal_rep_position: str | None = None,
    ) -> OrgSnapshot:
        """Create an org. Business kind pins tax plus legal head."""
        clean_name = name.strip()
        clean_slug = slug.strip().lower()
        if kind not in _ORG_KINDS:
            raise InvalidBusinessProfileError("Org kind is invalid.")
        if not (2 <= len(clean_name) <= 100):
            raise InvalidBusinessProfileError("Org name is invalid.")
        if kind == "business" and not (tax_code and legal_rep_name and legal_rep_id):
            raise InvalidBusinessProfileError(
                "Business orgs require tax_code and legal representative."
            )
        legal_status = "pending" if kind == "business" else "none"
        now = utcnow()
        org = self._orgs.create(
            generate_org_id(),
            owner_id,
            clean_name,
            clean_slug,
            description.strip(),
            kind,
            tax_code,
            legal_rep_name,
            legal_rep_id,
            legal_rep_position,
            legal_status,
            now,
        )
        return self._snapshot(org.id)

    def list_my_orgs(self, user_id: UUID, include_deleted: bool = False) -> list[OrgSnapshot]:
        """List orgs owned or joined by one user, hiding trash by default."""
        snapshots = [self._snapshot(org.id) for org in self._orgs.list_by_user(user_id)]
        if include_deleted:
            return snapshots
        return [item for item in snapshots if item.deleted_at is None]

    def update_org(
        self, org_id: UUID, user_id: UUID, name: str, description: str
    ) -> OrgSnapshot:
        """Owner renames or re-describes a live org."""
        self._require_live(org_id, user_id)
        clean_name = name.strip()
        if not (2 <= len(clean_name) <= 100):
            raise InvalidBusinessProfileError("Org name is invalid.")
        if len(description.strip()) > 500:
            raise InvalidBusinessProfileError("Org description is invalid.")
        now = utcnow()
        org = self._orgs.update_details(org_id, clean_name, description.strip(), now)
        assert org is not None
        return self._snapshot(org_id)

    def soft_delete_org(self, org_id: UUID, user_id: UUID) -> OrgSnapshot:
        """Owner moves an org to trash. Restorable, files stay on disk."""
        self._require_live(org_id, user_id)
        org = self._orgs.mark_deleted(org_id, utcnow())
        assert org is not None
        return self._snapshot(org_id)

    def restore_org(self, org_id: UUID, user_id: UUID) -> OrgSnapshot:
        """Owner brings a soft-deleted org back to the visible list."""
        org = self._require_owner(org_id, user_id)
        if getattr(org, "deleted_at", None) is None:
            raise InvalidBusinessProfileError("Organization is not deleted.")
        restored = self._orgs.mark_restored(org_id, utcnow())
        assert restored is not None
        return self._snapshot(org_id)

    def hard_delete_org(self, org_id: UUID, user_id: UUID) -> int:
        """Owner erases everything: rows plus the org folder and orphans."""
        self._require_owner(org_id, user_id)
        removed = self._orgs.delete_everything(org_id)
        swept = 0
        if self._store is not None:
            self._store.delete_org_dir(org_id)
            known = self._media.known_org_ids() if self._media is not None else set()
            swept = self._store.sweep_orphans(set(known))
        return swept if removed else 0

    def _check_media_ready(self) -> tuple[MediaRepository, MediaStore]:
        if self._media is None or self._store is None:
            raise InvalidBusinessProfileError("Media storage is not configured.")
        return self._media, self._store

    def upload_media(
        self, org_id: UUID, user_id: UUID, filename: str, mime: str, content: bytes
    ) -> MediaSnapshot:
        """Any member uploads one image/video into the org folder."""
        org = self._owned(org_id)
        if getattr(org, "deleted_at", None) is not None:
            raise OrgDeletedError("Organization is soft-deleted.")
        if not self._orgs.is_member(org_id, user_id):
            raise ForbiddenError("Only org members can upload media.")
        kind = media_kind(mime)
        if kind is None:
            raise UnsupportedMediaError("Only images and videos are allowed.")
        limit = self._max_image_bytes if kind == "image" else self._max_video_bytes
        if len(content) > limit:
            raise MediaTooLargeError("File exceeds the size limit.")
        media, store = self._check_media_ready()
        from core.ids import uuid7

        asset_id = uuid7()
        relative = store.save_typed(org_id, asset_id, mime, filename, content)
        now = utcnow()
        row = media.create_asset(asset_id, org_id, relative, mime, len(content), now)
        return MediaSnapshot(
            id=row.asset_id,
            org_id=org_id,
            kind=kind,
            mime=mime,
            size_bytes=len(content),
            file_url=f"/media/{relative}",
            created_at=row.created_at,
        )

    def list_media(self, org_id: UUID, user_id: UUID) -> list[MediaSnapshot]:
        """Newest-first gallery for members of a live org."""
        org = self._owned(org_id)
        if getattr(org, "deleted_at", None) is not None:
            raise OrgDeletedError("Organization is soft-deleted.")
        if not self._orgs.is_member(org_id, user_id):
            raise ForbiddenError("Only org members can view media.")
        media, _ = self._check_media_ready()
        snapshots: list[MediaSnapshot] = []
        for row in media.list_by_org(org_id):
            kind = media_kind(row.mime) or "image"
            snapshots.append(
                MediaSnapshot(
                    id=row.asset_id,
                    org_id=org_id,
                    kind=kind,
                    mime=row.mime,
                    size_bytes=int(row.size_bytes or 0),
                    file_url=f"/media/{row.file_url}",
                    created_at=row.created_at,
                )
            )
        return snapshots

    def delete_media(self, org_id: UUID, user_id: UUID, media_id: UUID) -> None:
        """Owner removes one gallery file: metadata row plus bytes."""
        self._require_live(org_id, user_id)
        media, store = self._check_media_ready()
        row = media.get_asset(media_id)
        if row is None or row.owner_id != org_id:
            raise NotFoundError("Media not found.")
        media.delete_asset(media_id)
        store.delete_file(row.file_url)

    def media_file(self, org_id: UUID, media_id: UUID) -> tuple[str, str]:
        """Resolve the absolute file path plus mime for streaming."""
        media, store = self._check_media_ready()
        row = media.get_asset(media_id)
        if row is None or row.owner_id != org_id:
            raise NotFoundError("Media not found.")
        return str(store.resolve(row.file_url)), row.mime
