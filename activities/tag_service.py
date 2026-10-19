"""Org-scoped tag catalog: lazy claims plus the public directory search."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from activities.interfaces import OrgTagStore
from activities.model import tag_fold, tag_slug
from core.exceptions import TagDeletedError
from core.security import utcnow

_MAX_TAGS = 10
_MAX_NAME = 40


@dataclass(frozen=True)
class PublicTagSnapshot:
    """One cross-org suggestion: slug plus the winning display name."""

    name: str
    slug: str


class TagService:
    """Tag rules: per-org canonical names, cross-org slug discovery."""

    def __init__(self, tags: OrgTagStore) -> None:
        self._tags = tags

    def search_public(
        self, query: str, limit: int = 20
    ) -> list[PublicTagSnapshot]:
        """Typeahead over every org's catalog, deduped by slug. The
        display name is the most frequent spelling (ties break by
        casefold-alphabetical order)."""
        names: dict[str, Counter[str]] = {}
        for row in self._tags.directory():
            names.setdefault(row.slug, Counter())[row.name] += 1
        needle = tag_fold(query.strip())
        items: list[PublicTagSnapshot] = []
        for slug, counter in names.items():
            name = sorted(
                counter.items(),
                key=lambda pair: (-pair[1], pair[0].casefold()),
            )[0][0]
            if needle and needle not in slug and needle not in tag_fold(name):
                continue
            items.append(PublicTagSnapshot(name=name, slug=slug))
        items.sort(key=lambda item: item.name.casefold())
        return items[:limit]

    def ensure(self, org_id: UUID, names: list[str] | None) -> list[str]:
        """Resolve display names to the org's canonical names, claiming
        new slugs lazily; output keeps user order and dedupes by slug."""
        canonical: list[str] = []
        seen: set[str] = set()
        for raw in names or []:
            slug = tag_slug(raw)
            if not slug or len(raw.strip()) > _MAX_NAME or slug in seen:
                continue
            seen.add(slug)
            row = self._tags.get(org_id, slug)
            if row is None:
                from core.ids import uuid7

                row, _ = self._tags.claim(
                    org_id, uuid7(), slug, raw.strip(), utcnow()
                )
            if row.deleted_at is not None:
                # The slug stays reserved while the tag is in the org
                # trash; a manager must restore it first.
                raise TagDeletedError("Tag is in the trash.")
            canonical.append(row.name)
            if len(canonical) >= _MAX_TAGS:
                break
        return canonical
