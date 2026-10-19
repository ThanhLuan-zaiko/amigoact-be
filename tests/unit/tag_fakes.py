"""In-memory OrgTagStore for tag service unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from uuid import UUID

from activities.interfaces import OrgTagStore
from activities.model import tag_slug

if TYPE_CHECKING:
    from tests.unit.activity_fakes import FakeActivities


class FakeOrgTags(OrgTagStore):
    """Catalog dict keyed by (org_id, slug); retag/usage delegate to
    the shared FakeActivities rows just like the real edge index."""

    def __init__(self, activities: FakeActivities) -> None:
        self.rows: dict[tuple[UUID, str], Any] = {}
        # Remembered edges of trashed tags: (org, slug) -> activity ids.
        self.trash_edges: dict[tuple[UUID, str], set[UUID]] = {}
        self.activities = activities

    def get(self, org_id, slug):  # noqa: ANN001, ANN202
        return self.rows.get((org_id, slug))

    def list(self, org_id):  # noqa: ANN001, ANN202
        return [
            row
            for (oid, _), row in self.rows.items()
            if oid == org_id
        ]

    def claim(self, org_id, tag_id, slug, name, now):  # noqa: ANN001, ANN202
        key = (org_id, slug)
        if key in self.rows:
            return self.rows[key], False
        row = SimpleNamespace(
            org_id=org_id, slug=slug, tag_id=tag_id, name=name,
            created_at=now, updated_at=now, deleted_at=None,
        )
        self.rows[key] = row
        return row, True

    def rename(self, org_id, row, slug, name, now):  # noqa: ANN001, ANN202
        # A new slug claims a fresh row; the old one stays for the
        # caller to remove after retag (crash-safe ordering).
        if slug != row.slug and (org_id, slug) in self.rows:
            return None
        updated = SimpleNamespace(
            org_id=org_id, slug=slug, tag_id=row.tag_id, name=name,
            created_at=row.created_at, updated_at=now, deleted_at=None,
        )
        self.rows[(org_id, slug)] = updated
        return updated

    def remove(self, org_id, slug):  # noqa: ANN001, ANN202
        self.rows.pop((org_id, slug), None)
        self.trash_edges.pop((org_id, slug), None)

    def snapshot_trash_edges(self, org_id, slug):  # noqa: ANN001, ANN202
        ids = self.trash_edges.setdefault((org_id, slug), set())
        for row in self.activities.rows.values():
            if row.org_id != org_id:
                continue
            if any(
                tag_slug(n) == slug for n in row.tag_names or []
            ):
                ids.add(row.id)

    def mark_trashed(self, org_id, slug, now):  # noqa: ANN001, ANN202
        row = self.rows.get((org_id, slug))
        if row is not None:
            row.deleted_at = now
            row.updated_at = now

    def restore_edges(self, org_id, slug, name, now):  # noqa: ANN001, ANN202
        attached = []
        skipped = 0
        for aid in self.trash_edges.get((org_id, slug), set()):
            row = self.activities.rows.get(aid)
            if row is None:
                continue
            names = list(row.tag_names or [])
            if slug in {tag_slug(n) for n in names}:
                continue
            if len(names) >= 10:
                skipped += 1
                continue
            names.append(name)
            row.tag_names = names
            row.updated_at = now
            attached.append(aid)
        return attached, skipped

    def mark_restored(self, org_id, slug, name, now):  # noqa: ANN001, ANN202
        row = self.rows.get((org_id, slug))
        if row is not None:
            row.deleted_at = None
            row.updated_at = now
        self.trash_edges.pop((org_id, slug), None)

    def trashed_usage(self, org_id):  # noqa: ANN001, ANN202
        counts: dict[str, int] = {}
        for (oid, slug), ids in self.trash_edges.items():
            if oid != org_id:
                continue
            counts[slug] = sum(
                1
                for aid in ids
                if (r := self.activities.rows.get(aid)) is not None
                and r.deleted_at is None
            )
        return counts

    def retag(self, org_id, slug, replacement, now):  # noqa: ANN001, ANN202
        touched = []
        for row in self.activities.rows.values():
            if row.org_id != org_id:
                continue
            names = list(row.tag_names or [])
            hit = next(
                (
                    i for i, n in enumerate(names)
                    if tag_slug(n) == slug
                ),
                None,
            )
            if hit is None:
                continue
            if replacement is None:
                names.pop(hit)
            else:
                names[hit] = replacement
            seen: set[str] = set()
            deduped = []
            for name in names:
                key = tag_slug(name)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(name)
            row.tag_names = deduped
            row.updated_at = now
            touched.append(row.id)
        return touched

    def usage(self, org_id):  # noqa: ANN001, ANN202
        counts: dict[str, int] = {}
        for row in self.activities.rows.values():
            if row.org_id != org_id or row.deleted_at is not None:
                continue
            for name in row.tag_names or []:
                slug = tag_slug(name)
                counts[slug] = counts.get(slug, 0) + 1
        return counts

    def directory(self):  # noqa: ANN202
        # Trashed rows leave the public surface (real store drops the
        # directory row on mark_trashed).
        return [
            SimpleNamespace(
                slug=row.slug, org_id=row.org_id, name=row.name
            )
            for row in self.rows.values()
            if getattr(row, "deleted_at", None) is None
        ]
