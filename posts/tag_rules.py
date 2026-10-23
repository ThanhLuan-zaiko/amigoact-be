"""Pure helpers for the 3-tag cap on board posts."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from core.tags import tag_slug

MAX_POST_TAGS = 3


class TagClaims(Protocol):
    """Catalog claim used when a post save names a tag."""

    def ensure(self, org_id: UUID, names: list[str] | None) -> list[str]:
        """Resolve names to the org's canonical spelling."""


def take_post_tags(names: list[str] | None) -> list[str]:
    """First 3 non-empty names, in order. ensure() dedupes by slug."""
    chosen: list[str] = []
    for raw in names or []:
        text = raw.strip() if isinstance(raw, str) else ""
        if not text:
            continue
        chosen.append(text)
        if len(chosen) >= MAX_POST_TAGS:
            break
    return chosen


def dedupe_tag_names(names: list[str]) -> list[str]:
    """Drop a later name whose slug already appeared."""
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        slug = tag_slug(name)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        out.append(name)
    return out
