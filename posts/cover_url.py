"""Public image path for one board post.

The cover asset wins. A video cover, or no cover, falls through to the
first linked image, then the first image block.
"""

from __future__ import annotations

import json
from typing import Protocol
from uuid import UUID

from posts.snapshots import public_media_url


class _PostMedia(Protocol):
    def list_media(self, post_id: UUID) -> list:
        """Attachment rows for one post."""


class _Assets(Protocol):
    def get_asset(self, asset_id: UUID) -> object | None:
        """Media metadata, or None."""


class CqlPostCovers:
    """Resolve a post row to a /media image path."""

    def __init__(self, posts: _PostMedia, media: _Assets) -> None:
        self._posts = posts
        self._media = media

    def cover_of(self, row: object) -> str | None:
        cover_id = getattr(row, "cover_media_id", None)
        if isinstance(cover_id, UUID):
            url = self._image(cover_id)
            if url is not None:
                return url
        post_id = getattr(row, "post_id", None)
        if isinstance(post_id, UUID):
            for link in self._posts.list_media(post_id):
                url = self._image(getattr(link, "asset_id", None))
                if url is not None:
                    return url
        for asset_id in _block_images(getattr(row, "blocks_json", None)):
            url = self._image(asset_id)
            if url is not None:
                return url
        return None

    def _image(self, asset_id: object) -> str | None:
        if not isinstance(asset_id, UUID):
            return None
        asset = self._media.get_asset(asset_id)
        if asset is None:
            return None
        mime = getattr(asset, "mime", "") or ""
        file_url = getattr(asset, "file_url", "") or ""
        if not mime.startswith("image/") or not file_url:
            return None
        return public_media_url(file_url)


def _block_images(raw: object) -> list[UUID]:
    if not isinstance(raw, str) or not raw:
        return []
    try:
        blocks = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(blocks, list):
        return []
    found: list[UUID] = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "image":
            continue
        try:
            found.append(UUID(str(block.get("asset_id"))))
        except (TypeError, ValueError):
            continue
    return found
