"""Feed-projection helpers shared by the activity store."""

from __future__ import annotations

from uuid import UUID

from activities.model import (
    ActivitiesByCategory,
    ActivitiesByOrg,
    ActivitiesBySlug,
    ActivitiesByStatus,
    ActivitiesByTag,
    Activity,
    tag_slug,
)
from activities.tag_model import (
    ActivityTagsByOrg,
    TrashedTagEdgesByOrg,
)


def _feeds(row: Activity) -> None:
    """Write every denormalized feed projection for one activity."""
    ActivitiesByOrg.create(
        org_id=row.org_id,
        start_at=row.start_at,
        activity_id=row.id,
        title=row.title,
        status=row.status,
        campus_id=row.campus_id,
    )
    ActivitiesByStatus.create(
        status=row.status,
        start_at=row.start_at,
        activity_id=row.id,
        org_id=row.org_id,
        title=row.title,
    )
    if row.category_id is not None:
        ActivitiesByCategory.create(
            category_id=row.category_id,
            start_at=row.start_at,
            activity_id=row.id,
            org_id=row.org_id,
            title=row.title,
        )
    for name in row.tag_names or []:
        ActivitiesByTag.create(
            tag_slug=tag_slug(name),
            start_at=row.start_at,
            activity_id=row.id,
            org_id=row.org_id,
            title=row.title,
            status=row.status,
        )
    ActivitiesBySlug.create(
        org_id=row.org_id,
        slug=row.slug,
        activity_id=row.id,
        title=row.title,
        status=row.status,
        start_at=row.start_at,
    )


def _clear_feeds(row: Activity, *, keep_slug: bool = False) -> None:
    """Delete feed rows at the coordinates of the passed snapshot."""
    ActivitiesByOrg.objects(
        org_id=row.org_id, start_at=row.start_at, activity_id=row.id
    ).delete()
    ActivitiesByStatus.objects(
        status=row.status, start_at=row.start_at, activity_id=row.id
    ).delete()
    if row.category_id is not None:
        ActivitiesByCategory.objects(
            category_id=row.category_id,
            start_at=row.start_at,
            activity_id=row.id,
        ).delete()
    for name in row.tag_names or []:
        ActivitiesByTag.objects(
            tag_slug=tag_slug(name),
            start_at=row.start_at,
            activity_id=row.id,
        ).delete()
    if not keep_slug:
        ActivitiesBySlug.objects(org_id=row.org_id, slug=row.slug).delete()


def _tag_edges(row: Activity) -> None:
    """Mirror tag_names into the per-org edge index."""
    for name in row.tag_names or []:
        ActivityTagsByOrg.create(
            org_id=row.org_id,
            tag_slug=tag_slug(name),
            activity_id=row.id,
        )


def _clear_tag_edges(row: Activity) -> None:
    """Drop the edge rows at the coordinates of the passed snapshot."""
    for name in row.tag_names or []:
        ActivityTagsByOrg.objects(
            org_id=row.org_id,
            tag_slug=tag_slug(name),
            activity_id=row.id,
        ).delete()


def _clear_trash_edges(row: Activity) -> None:
    """Purge maintenance: remembered tag-trash edges must only point at
    existing activities, so a hard delete drops its rows too."""
    for edge in TrashedTagEdgesByOrg.objects(org_id=row.org_id).all():
        if edge.activity_id == row.id:
            edge.delete()


def _hydrate(ids: list[UUID]) -> list[Activity]:
    """Resolve feed-row ids to full activities, preserving order."""
    rows = {
        row.id: row
        for row in (Activity.objects(id=i).first() for i in ids)
        if row is not None
    }
    return [rows[i] for i in ids if i in rows]
