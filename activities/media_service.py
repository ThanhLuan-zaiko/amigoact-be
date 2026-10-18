"""Business rules for the per-activity photo/video gallery."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from activities.interfaces import ActivityMediaStore, ActivityStore
from admin.interfaces import ModerationStore
from core.exceptions import (
    ForbiddenError,
    InvalidMediaRoleError,
    MediaTooLargeError,
    NotFoundError,
    UnsupportedMediaError,
)
from core.ids import uuid7
from core.media import MEDIA_MIMES, MediaStore, media_kind, normalize_image
from core.security import utcnow
from orgs.interfaces import MediaRepository, OrgRepository
from rbac.interfaces import AccessControl

_MEDIA_ROLES = {"cover", "gallery", "document"}


@dataclass(slots=True)
class ActivityMediaItem:
    """One gallery entry joined with its asset metadata."""

    asset_id: UUID
    position: int
    role: str
    caption: str | None
    file_url: str
    mime: str
    kind: str
    size_bytes: int
    original_name: str | None


class ActivityMediaService:
    """Manager-only writes; reads are open so the public detail page renders."""

    def __init__(
        self,
        *,
        activities: ActivityStore,
        orgs: OrgRepository,
        media: MediaRepository,
        entries: ActivityMediaStore,
        store: MediaStore,
        access: AccessControl,
        max_image_bytes: int,
        max_video_bytes: int,
        moderation: "ModerationStore | None" = None,
    ) -> None:
        self._activities = activities
        self._orgs = orgs
        self._media = media
        self._entries = entries
        self._store = store
        self._access = access
        self._max_image_bytes = max_image_bytes
        self._max_video_bytes = max_video_bytes
        self._moderation = moderation

    def _is_manager(self, org_id: UUID, actor_id: UUID) -> bool:
        org = self._orgs.get_by_id(org_id)
        if org is None or getattr(org, "deleted_at", None) is not None:
            raise NotFoundError("Organization not found.")
        return org.owner_id == actor_id or self._access.has_permission(
            org_id, actor_id, "activity:manage"
        )

    def _activity(self, activity_id: UUID) -> UUID:
        row = self._activities.get(activity_id)
        if row is None:
            raise NotFoundError("Activity not found.")
        return row.org_id

    def _snapshot(self, entry) -> ActivityMediaItem:
        asset = self._media.get_asset(entry.asset_id)
        mime = getattr(asset, "mime", None) or "application/octet-stream"
        return ActivityMediaItem(
            asset_id=entry.asset_id,
            position=entry.position,
            role=entry.role or "gallery",
            caption=entry.caption,
            file_url=getattr(asset, "file_url", "") or "",
            mime=mime,
            kind=media_kind(mime) or "document",
            size_bytes=getattr(asset, "size_bytes", 0) or 0,
            original_name=getattr(asset, "original_name", None),
        )

    def list_media(
        self, activity_id: UUID, viewer_id: UUID | None
    ) -> list[ActivityMediaItem]:
        """Public gallery read; unpublished activities stay manager-only."""
        org_id = self._activity(activity_id)
        row = self._activities.get(activity_id)
        assert row is not None
        if getattr(row, "status", None) != "published" and (
            viewer_id is None or not self._is_manager(org_id, viewer_id)
        ):
            raise NotFoundError("Activity not found.")
        return [
            self._snapshot(e) for e in self._entries.list_for_activity(
                activity_id
            )
        ]

    def upload(
        self,
        activity_id: UUID,
        user_id: UUID,
        filename: str,
        mime: str,
        content: bytes,
        caption: str | None,
        role: str = "gallery",
    ) -> ActivityMediaItem:
        """Manager uploads one image/video/document into the gallery."""
        org_id = self._activity(activity_id)
        if not self._is_manager(org_id, user_id):
            raise ForbiddenError("Only org managers can upload media.")
        if role not in _MEDIA_ROLES:
            raise InvalidMediaRoleError("Media role is invalid.")
        kind = media_kind(mime)
        if kind is None and role != "document":
            raise UnsupportedMediaError("Only images and videos are allowed.")
        limit = (
            self._max_image_bytes if kind == "image"
            else self._max_video_bytes
        )
        if len(content) > limit:
            raise MediaTooLargeError("File exceeds the size limit.")
        if kind == "image":
            try:
                mime, content = normalize_image(content, mime)
            except ValueError as exc:
                raise MediaTooLargeError(
                    "Image exceeds the pixel limit."
                ) from exc
        if kind is None:
            mime = mime if mime in MEDIA_MIMES else "application/octet-stream"
        asset_id = uuid7()
        # Bytes live under the OWNING ORG folder (orgs/<org_id>/), never
        # under orgs/<activity_id>/: the orphan sweep whitelists org
        # folders, so activity-named folders would be wiped on any org
        # hard delete. owner_id still records the activity.
        relative = self._store.save_typed(
            org_id, asset_id, mime, filename, content
        )
        now = utcnow()
        self._media.create_asset(
            asset_id,
            activity_id,
            relative,
            mime,
            len(content),
            now,
            "gallery",
            file_hash=hashlib.sha256(content).hexdigest(),
            uploader_id=user_id,
            original_name=filename,
            owner_type="activity",
        )
        if self._moderation is not None:
            self._moderation.enqueue(uuid7(), asset_id, now)
        entries = self._entries.list_for_activity(activity_id)
        position = (max(e.position for e in entries) + 1) if entries else 0
        entry = self._entries.create(
            activity_id, position, asset_id, role, caption
        )
        return self._snapshot(entry)

    def update_entry(
        self,
        activity_id: UUID,
        user_id: UUID,
        asset_id: UUID,
        caption: str | None,
        role: str | None,
    ) -> ActivityMediaItem:
        """Manager edits caption/role of one gallery entry."""
        org_id = self._activity(activity_id)
        if not self._is_manager(org_id, user_id):
            raise ForbiddenError("Only org managers can edit media.")
        entry = self._find(activity_id, asset_id)
        if role is not None and role not in _MEDIA_ROLES:
            raise InvalidMediaRoleError("Media role is invalid.")
        self._entries.update(
            activity_id,
            entry.position,
            asset_id,
            caption if caption is not None else entry.caption,
            role or entry.role or "gallery",
        )
        entry.caption = caption if caption is not None else entry.caption
        if role is not None:
            entry.role = role
        return self._snapshot(entry)

    def delete(self, activity_id: UUID, user_id: UUID, asset_id: UUID) -> None:
        """Manager removes one entry, its asset row, and the stored file."""
        org_id = self._activity(activity_id)
        if not self._is_manager(org_id, user_id):
            raise ForbiddenError("Only org managers can delete media.")
        entry = self._find(activity_id, asset_id)
        self._entries.delete(activity_id, entry.position, asset_id)
        row = self._media.delete_asset(asset_id)
        if row is not None:
            self._store.delete_file(row.file_url)

    def _find(self, activity_id: UUID, asset_id: UUID):
        for entry in self._entries.list_for_activity(activity_id):
            if entry.asset_id == asset_id:
                return entry
        raise NotFoundError("Media not found.")
