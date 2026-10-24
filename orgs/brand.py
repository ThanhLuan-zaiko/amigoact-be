"""Public brand URL (logo or cover) for an org's own gallery asset."""

from __future__ import annotations

from uuid import UUID

from core.media_rules import is_gallery_asset
from orgs.interfaces import MediaRepository


def brand_url(
    media: MediaRepository | None,
    org_id: UUID,
    asset_id: UUID | None,
    role: str,
) -> str | None:
    """Brand pointer -> URL, only when the asset belongs to this org."""
    if asset_id is None or media is None:
        return None
    asset = media.get_asset(asset_id)
    if (
        asset is None
        or not is_gallery_asset(asset, org_id)
        or asset.role != role
        or getattr(asset, "deleted_at", None) is not None
    ):
        return None
    return f"/media/{asset.file_url}"
