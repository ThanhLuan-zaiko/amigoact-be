"""cqlengine persistence for the org-scoped tag catalog (tags_by_org).

LWT claims stay raw CQL like every other uniqueness claim in the
codebase; the rest goes through the models in tag_model.py.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID


from activities.interfaces import OrgTagStore
from activities.model import ActivitiesByTag, ActivitiesTrashByOrg, Activity
from activities.model import tag_slug
from activities.tag_model import (
    ActivityTagsByOrg,
    PublicTagDirectory,
    TagByOrg,
    TrashedTagEdgesByOrg,
)
from core.exceptions import TagDeletedError
from core.cql import run as cql_run

DIRECTORY_BUCKET = "all"
_MAX_ACTIVITY_TAGS = 10


def _dedupe(names: list[str]) -> list[str]:
    """Drop later names whose slug already appeared."""
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        slug = tag_slug(name)
        if slug in seen:
            continue
        seen.add(slug)
        out.append(name)
    return out


class CqlOrgTagStore(OrgTagStore):
    """Slug-claim store per org; the catalog row is the uniqueness lock."""

    def __init__(self, keyspace: str) -> None:
        self._keyspace = keyspace

    def get(self, org_id: UUID, slug: str) -> TagByOrg | None:
        return TagByOrg.objects(org_id=org_id, slug=slug).first()

    def list(self, org_id: UUID) -> list[TagByOrg]:
        return list(TagByOrg.objects(org_id=org_id).all())

    def _directory_write(
        self, org_id: UUID, slug: str, name: str
    ) -> None:
        PublicTagDirectory.create(
            bucket=DIRECTORY_BUCKET, slug=slug, org_id=org_id, name=name
        )

    def _directory_delete(self, org_id: UUID, slug: str) -> None:
        PublicTagDirectory.objects(
            bucket=DIRECTORY_BUCKET, slug=slug, org_id=org_id
        ).delete()

    def claim(
        self,
        org_id: UUID,
        tag_id: UUID,
        slug: str,
        name: str,
        now: datetime,
    ) -> tuple[TagByOrg, bool]:
        """Race-safe create: losers read back the winner's row."""
        applied = cql_run(
            f"INSERT INTO {self._keyspace}.tags_by_org"
            " (org_id, slug, tag_id, name, created_at, updated_at)"
            " VALUES (%s, %s, %s, %s, %s, %s) IF NOT EXISTS",
            [org_id, slug, tag_id, name, now, now],
        )
        if applied.was_applied:
            self._directory_write(org_id, slug, name)
            return (
                TagByOrg(
                    org_id=org_id,
                    slug=slug,
                    tag_id=tag_id,
                    name=name,
                    created_at=now,
                    updated_at=now,
                ),
                True,
            )
        existing = self.get(org_id, slug)
        if existing is None:  # pragma: no cover - winner just deleted
            return (
                TagByOrg(
                    org_id=org_id,
                    slug=slug,
                    tag_id=tag_id,
                    name=name,
                    created_at=now,
                    updated_at=now,
                ),
                False,
            )
        return existing, False

    def rename(
        self,
        org_id: UUID,
        row: TagByOrg,
        slug: str,
        name: str,
        now: datetime,
    ) -> TagByOrg | None:
        if slug == row.slug:
            TagByOrg.objects(org_id=org_id, slug=slug).update(
                name=name, updated_at=now
            )
            self._directory_write(org_id, slug, name)
            return TagByOrg(
                org_id=org_id,
                slug=slug,
                tag_id=row.tag_id,
                name=name,
                created_at=row.created_at,
                updated_at=now,
            )
        applied = cql_run(
            f"INSERT INTO {self._keyspace}.tags_by_org"
            " (org_id, slug, tag_id, name, created_at, updated_at)"
            " VALUES (%s, %s, %s, %s, %s, %s) IF NOT EXISTS",
            [org_id, slug, row.tag_id, name, row.created_at, now],
        )
        if not applied.was_applied:
            return None
        self._directory_write(org_id, slug, name)
        return TagByOrg(
            org_id=org_id,
            slug=slug,
            tag_id=row.tag_id,
            name=name,
            created_at=row.created_at,
            updated_at=now,
        )

    def remove(self, org_id: UUID, slug: str) -> None:
        TagByOrg.objects(org_id=org_id, slug=slug).delete()
        self._directory_delete(org_id, slug)
        TrashedTagEdgesByOrg.objects(org_id=org_id, tag_slug=slug).delete()

    def snapshot_trash_edges(self, org_id: UUID, slug: str) -> None:
        for edge in ActivityTagsByOrg.objects(
            org_id=org_id, tag_slug=slug
        ).all():
            TrashedTagEdgesByOrg.create(
                org_id=org_id,
                tag_slug=slug,
                activity_id=edge.activity_id,
            )

    def mark_trashed(self, org_id: UUID, slug: str, now: datetime) -> None:
        TagByOrg.objects(org_id=org_id, slug=slug).update(
            deleted_at=now, updated_at=now
        )
        self._directory_delete(org_id, slug)

    def restore_edges(
        self, org_id: UUID, slug: str, name: str, now: datetime
    ) -> tuple[list[UUID], int]:
        attached: list[UUID] = []
        skipped = 0
        edges = list(
            TrashedTagEdgesByOrg.objects(
                org_id=org_id, tag_slug=slug
            ).all()
        )
        for edge in edges:
            row = Activity.objects(id=edge.activity_id).first()
            if row is None:
                continue
            names = list(row.tag_names or [])
            if slug in {tag_slug(n) for n in names}:
                continue
            if len(names) >= _MAX_ACTIVITY_TAGS:
                skipped += 1
                continue
            names.append(name)
            Activity.objects(id=row.id).update(
                tag_names=names, updated_at=now
            )
            if row.deleted_at is None:
                ActivitiesByTag.create(
                    tag_slug=slug,
                    start_at=row.start_at,
                    activity_id=row.id,
                    org_id=org_id,
                    title=row.title,
                    status=row.status,
                )
            ActivityTagsByOrg.create(
                org_id=org_id, tag_slug=slug, activity_id=row.id
            )
            attached.append(row.id)
        return attached, skipped

    def mark_restored(
        self, org_id: UUID, slug: str, name: str, now: datetime
    ) -> None:
        TagByOrg.objects(org_id=org_id, slug=slug).update(
            deleted_at=None, updated_at=now
        )
        self._directory_write(org_id, slug, name)
        TrashedTagEdgesByOrg.objects(org_id=org_id, tag_slug=slug).delete()

    def trashed_usage(self, org_id: UUID) -> dict[str, int]:
        trashed = {
            row.activity_id
            for row in ActivitiesTrashByOrg.objects(org_id=org_id).all()
        }
        counts: dict[str, int] = {}
        for edge in TrashedTagEdgesByOrg.objects(org_id=org_id).all():
            if edge.activity_id in trashed:
                continue
            counts[edge.tag_slug] = counts.get(edge.tag_slug, 0) + 1
        return counts

    def guard_replacement(self, org_id: UUID, replacement: str) -> None:
        """Refuse a personal rename onto a slug reserved in the trash."""
        row = self.get(org_id, tag_slug(replacement.strip()))
        if row is not None and row.deleted_at is not None:
            raise TagDeletedError("Tag is in the trash.")

    def _owned_name(
        self, org_id: UUID, replacement: str, now: datetime
    ) -> str:
        """Org-canonical spelling, claiming a slug the catalog lacks."""
        cleaned = replacement.strip()
        new_slug = tag_slug(cleaned)
        row = self.get(org_id, new_slug)
        if row is None:
            from core.ids import uuid7

            row, _created = self.claim(
                org_id, uuid7(), new_slug, cleaned, now
            )
        if row.deleted_at is not None:
            raise TagDeletedError("Tag is in the trash.")
        return row.name

    def retag(
        self,
        org_id: UUID,
        slug: str,
        replacement: str | None,
        now: datetime,
        only: set[UUID] | None = None,
    ) -> list[UUID]:
        # A personal rename must not overwrite the catalog's spelling
        # with the user's, and must not touch anyone else's activities.
        if only is not None and replacement is not None:
            replacement = self._owned_name(org_id, replacement, now)
        touched: list[UUID] = []
        edges = list(
            ActivityTagsByOrg.objects(org_id=org_id, tag_slug=slug).all()
        )
        for edge in edges:
            if only is not None and edge.activity_id not in only:
                continue
            row = Activity.objects(id=edge.activity_id).first()
            names = list(row.tag_names or []) if row is not None else []
            hit = next(
                (
                    index
                    for index, value in enumerate(names)
                    if tag_slug(value) == slug
                ),
                None,
            )
            if row is None or hit is None:
                # Edge without a matching tag/activity: drop the stale row.
                edge.delete()
                continue
            if replacement is None:
                names.pop(hit)
            else:
                names[hit] = replacement
            new_names = _dedupe(names)
            Activity.objects(id=row.id).update(
                tag_names=new_names, updated_at=now
            )
            if row.deleted_at is None:
                for name in row.tag_names or []:
                    ActivitiesByTag.objects(
                        tag_slug=tag_slug(name),
                        start_at=row.start_at,
                        activity_id=row.id,
                    ).delete()
                for name in new_names:
                    ActivitiesByTag.create(
                        tag_slug=tag_slug(name),
                        start_at=row.start_at,
                        activity_id=row.id,
                        org_id=org_id,
                        title=row.title,
                        status=row.status,
                    )
            edge.delete()
            for name in new_names:
                ActivityTagsByOrg.create(
                    org_id=org_id,
                    tag_slug=tag_slug(name),
                    activity_id=row.id,
                )
            touched.append(row.id)
            if only is None and replacement:
                new_slug = tag_slug(replacement)
                if new_slug != slug:
                    from activities.user_tag_activities import follow_author

                    follow_author(
                        self._keyspace, row, org_id, slug, new_slug,
                        replacement, now,
                    )
        return touched

    def usage(self, org_id: UUID) -> dict[str, int]:
        trashed = {
            row.activity_id
            for row in ActivitiesTrashByOrg.objects(org_id=org_id).all()
        }
        counts: dict[str, int] = {}
        for edge in ActivityTagsByOrg.objects(org_id=org_id).all():
            if edge.activity_id in trashed:
                continue
            counts[edge.tag_slug] = counts.get(edge.tag_slug, 0) + 1
        return counts

    def directory(self) -> list[PublicTagDirectory]:
        return list(
            PublicTagDirectory.objects(bucket=DIRECTORY_BUCKET).all()
        )
