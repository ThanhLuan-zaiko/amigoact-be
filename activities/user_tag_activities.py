"""Personal-tag edges for activities. Mirrors the post edge book."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from activities.interfaces import ActivityEvents
from core.tags import tag_slug

_MAX_NAME = 40
_LIMIT = 20


class ActivityHeads(Protocol):
    """The bit of the activity store this catalog needs."""

    def get(self, activity_id: UUID) -> object | None:
        """Canonical activity, or None."""


class ActivityRetag(Protocol):
    """Org-catalog rewrite limited to activities the caller actually owns."""

    def guard_replacement(self, org_id: UUID, replacement: str) -> None:
        """Refuse a slug that org has sitting in the trash."""

    def retag(
        self,
        org_id: UUID,
        slug: str,
        replacement: str | None,
        now: datetime,
        only: set[UUID] | None = None,
    ) -> list[UUID]:
        """Rewrite tag_names. `only` keeps every other activity put."""


class CatalogBook(Protocol):
    """Edge store plus the personal name row a catalog rename may insert."""

    def activities_for(self, user_id: UUID, slug: str) -> list:
        """Edges for one slug."""

    def activity_slugs_of(self, user_id: UUID, activity_id: UUID) -> list[str]:
        """Slugs last saved on this activity."""

    def add_activity_edge(
        self, user_id: UUID, slug: str, activity_id: UUID, org_id: UUID
    ) -> None:
        """Insert one edge."""

    def remove_activity_edge(
        self, user_id: UUID, slug: str, activity_id: UUID
    ) -> None:
        """Delete one edge."""

    def write_activity_set(
        self,
        user_id: UUID,
        activity_id: UUID,
        org_id: UUID,
        slugs: list[str],
    ) -> None:
        """Replace the slug set, or delete it when empty."""

    def get(self, user_id: UUID, slug: str) -> object | None:
        """Personal name row, or None."""

    def insert(
        self, user_id: UUID, slug: str, name: str, now: datetime
    ) -> bool:
        """Create the personal name when the catalog slug is new to them."""


class ActivityEdges(Protocol):
    """Personal activity edges. The cql store implements this."""

    def activities_for(self, user_id: UUID, slug: str) -> list:
        """Edges for one slug."""

    def activity_slugs_of(self, user_id: UUID, activity_id: UUID) -> list[str]:
        """Slugs last saved on this activity."""

    def add_activity_edge(
        self, user_id: UUID, slug: str, activity_id: UUID, org_id: UUID
    ) -> None:
        """Insert one edge."""

    def remove_activity_edge(
        self, user_id: UUID, slug: str, activity_id: UUID
    ) -> None:
        """Delete one edge."""

    def write_activity_set(
        self,
        user_id: UUID,
        activity_id: UUID,
        org_id: UUID,
        slugs: list[str],
    ) -> None:
        """Replace the slug set, or delete it when empty."""

    def activity_sets_for(self, user_id: UUID) -> list:
        """Every activity set this user has written."""


@dataclass(frozen=True)
class UserTagActivity:
    """An activity the tags rail can open."""

    activity_id: UUID
    org_id: UUID
    title: str
    draft: bool


def _slugs(names: list[str] | None) -> list[str]:
    """Slugs in order, skipping blanks, long names, and duplicates."""
    picked: list[str] = []
    seen: set[str] = set()
    for raw in names or []:
        name = raw.strip() if isinstance(raw, str) else ""
        slug = tag_slug(name)
        if not slug or len(name) > _MAX_NAME or slug in seen:
            continue
        seen.add(slug)
        picked.append(slug)
    return picked


def _visible(row: object | None, slug: str) -> bool:
    if row is None or getattr(row, "deleted_at", None) is not None:
        return False
    names = getattr(row, "tag_names", None) or []
    return slug in {tag_slug(name) for name in names}


def bind(
    store: ActivityEdges,
    user_id: UUID,
    org_id: UUID,
    activity_id: UUID,
    names: list[str] | None,
) -> None:
    """Point this activity at the slugs it carries now."""
    wanted = _slugs(names)
    previous = set(store.activity_slugs_of(user_id, activity_id))
    current = set(wanted)
    for slug in previous - current:
        store.remove_activity_edge(user_id, slug, activity_id)
    for slug in current - previous:
        store.add_activity_edge(user_id, slug, activity_id, org_id)
    store.write_activity_set(user_id, activity_id, org_id, wanted)


def drop(store: ActivityEdges, user_id: UUID, slug: str) -> None:
    """Forget every activity edge for one slug."""
    for edge in store.activities_for(user_id, slug):
        store.remove_activity_edge(user_id, slug, edge.activity_id)
    for bundle in store.activity_sets_for(user_id):
        if slug not in (bundle.slugs or []):
            continue
        store.write_activity_set(
            user_id,
            bundle.activity_id,
            bundle.org_id,
            [item for item in bundle.slugs if item != slug],
        )


def move(store: ActivityEdges, user_id: UUID, old: str, new: str) -> None:
    """Retarget edges and sets when a personal slug changes."""
    for edge in list(store.activities_for(user_id, old)):
        store.remove_activity_edge(user_id, old, edge.activity_id)
        store.add_activity_edge(user_id, new, edge.activity_id, edge.org_id)
    for bundle in store.activity_sets_for(user_id):
        if old not in (bundle.slugs or []):
            continue
        store.write_activity_set(
            user_id,
            bundle.activity_id,
            bundle.org_id,
            [new if item == old else item for item in bundle.slugs],
        )


def orgs(store: ActivityEdges, user_id: UUID, slug: str) -> set[UUID]:
    """Orgs whose activities this user edged to the slug."""
    return {edge.org_id for edge in store.activities_for(user_id, slug)}


def rewrite_owned(
    store: ActivityEdges,
    retagger: ActivityRetag | None,
    events: ActivityEvents | None,
    user_id: UUID,
    slug: str,
    replacement: str | None,
    now: datetime,
) -> None:
    """Rewrite tag_names on this user's activities and nowhere else.

    A same-slug spelling change stays in the personal book. Activity
    names keep the org catalog's spelling, so the next save does not
    flip them back. A new slug is refused before any write when one
    of the touched orgs has that slug in the trash.
    """
    if retagger is None:
        return
    if replacement is not None and tag_slug(replacement) == slug:
        return
    by_org: dict[UUID, set[UUID]] = {}
    for edge in store.activities_for(user_id, slug):
        by_org.setdefault(edge.org_id, set()).add(edge.activity_id)
    if replacement is not None:
        for org_id in by_org:
            retagger.guard_replacement(org_id, replacement)
    action = "renamed" if replacement is not None else "detached"
    hint = tag_slug(replacement) if replacement is not None else slug
    for org_id, ids in by_org.items():
        retagger.retag(org_id, slug, replacement, now, only=ids)
        _hint(events, org_id, action, hint, user_id)


def follow_catalog(
    store: CatalogBook,
    user_id: UUID,
    org_id: UUID,
    activity_id: UUID,
    old: str,
    new: str,
    new_name: str,
    now: datetime,
) -> None:
    """Move the author's edge onto the slug the org catalog just wrote."""
    if not new or new == old:
        return
    store.remove_activity_edge(user_id, old, activity_id)
    present = {
        edge.activity_id for edge in store.activities_for(user_id, new)
    }
    if activity_id not in present:
        store.add_activity_edge(user_id, new, activity_id, org_id)
    merged: list[str] = []
    seen: set[str] = set()
    for item in store.activity_slugs_of(user_id, activity_id):
        slug = new if item == old else item
        if slug in seen:
            continue
        seen.add(slug)
        merged.append(slug)
    if new not in seen:
        merged.append(new)
    store.write_activity_set(user_id, activity_id, org_id, merged)
    if store.get(user_id, new) is None:
        store.insert(user_id, new, new_name, now)


def follow_author(
    keyspace: str,
    row: object,
    org_id: UUID,
    old: str,
    new: str,
    new_name: str,
    now: datetime,
) -> None:
    """Catalog slug changes must not leave the author's rail behind."""
    owner = getattr(row, "created_by", None)
    activity_id = getattr(row, "id", None)
    if owner is None or activity_id is None:
        return
    from activities.user_tag_store import CqlUserTagStore

    follow_catalog(
        CqlUserTagStore(keyspace),
        owner,
        org_id,
        activity_id,
        old,
        new,
        new_name,
        now,
    )


def _hint(
    events: ActivityEvents | None,
    org_id: UUID,
    action: str,
    slug: str,
    actor_id: UUID,
) -> None:
    if events is None:
        return
    try:
        events.tags_changed(org_id, action, slug, actor_id)
    except Exception:  # noqa: BLE001 - live fan-out is advisory
        pass


def collect(
    store: ActivityEdges,
    heads: ActivityHeads,
    user_id: UUID,
    slug: str,
) -> tuple[int, list[UserTagActivity]]:
    """Visible activities for one tag. The list stops at the rail cap."""
    total = 0
    found: list[UserTagActivity] = []
    for edge in store.activities_for(user_id, slug):
        row = heads.get(edge.activity_id)
        if not _visible(row, slug):
            continue
        total += 1
        if len(found) >= _LIMIT:
            continue
        status = getattr(row, "status", "draft") or "draft"
        title = (getattr(row, "title", "") or "").strip()
        found.append(
            UserTagActivity(
                activity_id=edge.activity_id,
                org_id=edge.org_id,
                title=title,
                draft=status == "draft",
            )
        )
    return total, found
