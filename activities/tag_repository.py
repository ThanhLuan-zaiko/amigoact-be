"""cqlengine persistence for the global tag catalog (tags_by_slug)."""

from __future__ import annotations

import unicodedata
from datetime import datetime
from uuid import UUID

from cassandra.cqlengine.connection import get_session

from activities.interfaces import TagStore
from activities.model import TagBySlug


def _fold(value: str) -> str:
    """Lowercase ASCII fold for substring matching in search()."""
    text = unicodedata.normalize("NFKD", value)
    text = text.replace("đ", "d").replace("Đ", "D")
    return "".join(
        ch for ch in text if not unicodedata.combining(ch)
    ).lower()


class CqlTagStore(TagStore):
    """Slug-claim store; the catalog row itself is the uniqueness lock."""

    def __init__(self, keyspace: str) -> None:
        self._keyspace = keyspace

    def get_by_slug(self, slug: str) -> TagBySlug | None:
        return TagBySlug.objects(slug=slug).first()

    def claim(
        self, tag_id: UUID, slug: str, name: str, now: datetime
    ) -> TagBySlug:
        """Race-safe create: losers read back the winner's row."""
        session = get_session()
        applied = session.execute(
            f"INSERT INTO {self._keyspace}.tags_by_slug"
            " (slug, tag_id, name, created_at)"
            " VALUES (%s, %s, %s, %s) IF NOT EXISTS",
            [slug, tag_id, name, now],
        )
        if applied.was_applied:
            return TagBySlug(
                slug=slug, tag_id=tag_id, name=name, created_at=now
            )
        existing = self.get_by_slug(slug)
        if existing is None:  # pragma: no cover - winner just deleted
            return TagBySlug(
                slug=slug, tag_id=tag_id, name=name, created_at=now
            )
        return existing

    def search(self, query: str, limit: int = 20) -> list[TagBySlug]:
        needle = _fold(query.strip())
        rows = [
            row
            for row in TagBySlug.objects.all()
            if not needle
            or needle in row.slug
            or needle in _fold(row.name)
        ]
        rows.sort(key=lambda row: row.name.lower())
        return rows[:limit]
