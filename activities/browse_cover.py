"""Cover picture for one activity: the cover-role image, else the first image.

Activity media is owned by the activity rather than the org, so the org
gallery check does not apply. The same asset checks as the org preview
still do: present, not deleted, active upload, image kind.
"""

from __future__ import annotations

from uuid import UUID

from activities.edge_interfaces import ActivityMediaStore
from core.media import media_kind
from orgs.interfaces import MediaRepository


def cover_url(
    entries: ActivityMediaStore,
    media: MediaRepository,
    activity_id: UUID,
) -> str | None:
    """Public image URL for the card, or None when no usable image exists."""
    covers: list[str] = []
    images: list[str] = []
    for entry in entries.list_for_activity(activity_id):
        asset = media.get_asset(entry.asset_id)
        if asset is None or getattr(asset, "deleted_at", None) is not None:
            continue
        if (getattr(asset, "upload_status", None) or "active") != "active":
            continue
        if media_kind(asset.mime or "") != "image":
            continue
        url = f"/media/{asset.file_url}"
        (covers if entry.role == "cover" else images).append(url)
    ordered = covers + images
    return ordered[0] if ordered else None
