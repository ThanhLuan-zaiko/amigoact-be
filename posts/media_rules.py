"""Post media validation and attachment cleanup (no FastAPI here).

Every asset a post references (legacy attachments, cover, image/video
blocks) must be a live asset owned by the same org with the right mime
family. Hard delete purges the post's "attachment"-role uploads; gallery
or brand assets reused in an article are never touched.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from core.exceptions import NotFoundError
from core.media import MediaStore
from orgs.interfaces import MediaRepository
from posts.blocks import MAX_MEDIA_BLOCKS, media_refs

MAX_ATTACHMENTS = 4


class PostMediaRules:
    """Validates referenced assets; optionally deletes attachment bytes."""

    def __init__(
        self, media: MediaRepository, files: MediaStore | None = None
    ) -> None:
        self._media = media
        self._files = files

    def _asset(self, org_id: UUID, asset_id: UUID, family: str):  # noqa: ANN202
        asset = self._media.get_asset(asset_id)
        if (
            asset is None
            or asset.owner_id != org_id
            or not (asset.mime or "").startswith(f"{family}/")
            or (asset.upload_status or "active") != "active"
        ):
            raise NotFoundError("Attachment not found.")
        return asset

    def attachments(self, org_id: UUID, media_ids: list[UUID]) -> list[UUID]:
        """Legacy image strip: deduped, capped, images only."""
        ids = list(dict.fromkeys(media_ids))[:MAX_ATTACHMENTS]
        return [self._asset(org_id, i, "image").asset_id for i in ids]

    def article(
        self, org_id: UUID, blocks: list[Any], cover_media_id: UUID | None
    ) -> list[UUID]:
        """Cover (image) then block media in document order, deduped."""
        refs = media_refs(blocks)
        if len(refs) > MAX_MEDIA_BLOCKS:
            raise NotFoundError("Too many media blocks.")
        ordered: list[UUID] = []
        if cover_media_id is not None:
            ordered.append(self._asset(org_id, cover_media_id, "image").asset_id)
        for asset_id, family in refs:
            if asset_id not in ordered:
                ordered.append(self._asset(org_id, asset_id, family).asset_id)
        return ordered

    def purge_attachments(self, org_id: UUID, asset_ids: list[UUID]) -> int:
        """Delete attachment-role assets (metadata + bytes); best-effort."""
        removed = 0
        for asset_id in dict.fromkeys(asset_ids):
            asset = self._media.get_asset(asset_id)
            if (
                asset is None
                or asset.owner_id != org_id
                or (getattr(asset, "role", None) or "gallery") != "attachment"
            ):
                continue
            self._media.delete_asset(asset_id)
            if self._files is not None:
                try:
                    self._files.delete_file(asset.file_url)
                except Exception:  # noqa: BLE001 - disk cleanup is best-effort
                    pass
            removed += 1
        return removed
