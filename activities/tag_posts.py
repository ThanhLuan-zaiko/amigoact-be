"""Port the tag catalog uses to keep post edges in step.

The concrete index lives in posts/. This module only describes the
calls curation makes, so activities never imports that feature.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID


class PostTagMirror(Protocol):
    """Subset of the post tag index that catalog curation calls."""

    def usage(self, org_id: UUID) -> dict[str, int]:
        """Slug -> published posts."""

    def trashed_usage(self, org_id: UUID) -> dict[str, int]:
        """Slug -> remembered edges of posts that are not trashed."""

    def retag(
        self,
        org_id: UUID,
        slug: str,
        replacement: str | None,
        now: datetime,
    ) -> None:
        """Rewrite post tag_names for one slug."""

    def snapshot_trash(self, org_id: UUID, slug: str) -> None:
        """Remember live post edges before a soft delete."""

    def restore(
        self, org_id: UUID, slug: str, name: str, now: datetime
    ) -> None:
        """Re-attach remembered posts, honoring the post tag cap."""

    def forget_slug(self, org_id: UUID, slug: str) -> None:
        """Drop remembered post edges for one slug."""


class PostTagBridge:
    """No-op when posts are not wired (unit tests of activity tags)."""

    def __init__(self, index: PostTagMirror | None) -> None:
        self._index = index

    def counts(self, org_id: UUID, trash: bool) -> dict[str, int]:
        if self._index is None:
            return {}
        if trash:
            return self._index.trashed_usage(org_id)
        return self._index.usage(org_id)

    def retag(
        self,
        org_id: UUID,
        slug: str,
        replacement: str | None,
        now: datetime,
    ) -> None:
        if self._index is not None:
            self._index.retag(org_id, slug, replacement, now)

    def snapshot(self, org_id: UUID, slug: str) -> None:
        if self._index is not None:
            self._index.snapshot_trash(org_id, slug)

    def restore(
        self, org_id: UUID, slug: str, name: str, now: datetime
    ) -> None:
        if self._index is not None:
            self._index.restore(org_id, slug, name, now)

    def forget(self, org_id: UUID, slug: str) -> None:
        if self._index is not None:
            self._index.forget_slug(org_id, slug)
