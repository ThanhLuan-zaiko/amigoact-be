"""Community tag catalog: dedupe-by-slug search plus lazy claims."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from activities.interfaces import TagStore
from activities.model import tag_slug
from core.security import utcnow

_MAX_TAGS = 10
_MAX_NAME = 40


@dataclass(frozen=True)
class TagSnapshot:
    """Flat catalog row for pickers and filter chips."""

    id: UUID
    name: str
    slug: str


class TagService:
    """Folksonomy rules: canonical slugs dedupe every spelling variant."""

    def __init__(self, tags: TagStore) -> None:
        self._tags = tags

    def search(self, query: str, limit: int = 20) -> list[TagSnapshot]:
        """Typeahead surface: folded substring match over the catalog."""
        return [
            TagSnapshot(id=row.tag_id, name=row.name, slug=row.slug)
            for row in self._tags.search(query, limit)
        ]

    def ensure(self, names: list[str] | None) -> list[str]:
        """Resolve display names to canonical catalog names, claiming new
        slugs lazily; output keeps user order and dedupes by slug."""
        canonical: list[str] = []
        seen: set[str] = set()
        for raw in names or []:
            slug = tag_slug(raw)
            if not slug or len(raw.strip()) > _MAX_NAME or slug in seen:
                continue
            seen.add(slug)
            row = self._tags.get_by_slug(slug)
            if row is None:
                from core.ids import uuid7

                row = self._tags.claim(
                    uuid7(), slug, raw.strip(), utcnow()
                )
            canonical.append(row.name)
            if len(canonical) >= _MAX_TAGS:
                break
        return canonical
