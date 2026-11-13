"""Tags on activities. They share the organization's tag catalog with posts, so one
tag such as #moi-truong groups the posts and the activities about the same thing."""

import uuid
from collections import defaultdict
from typing import Any

from fastapi import status
from sqlalchemy import Select, delete, false, func, or_, select
from sqlalchemy.orm import Session

from src.auth.errors import api_error
from src.models.activities import Activity
from src.models.organizations import Organization
from src.models.tags import ActivityTag, Tag
from src.organizations.access import get_access
from src.posts.rules import tag_slug, tag_word_patterns
from src.posts.tags import resolve_tags


def set_activity_tags(
    db: Session, activity_id: uuid.UUID, org_id: uuid.UUID, names: list[str]
) -> None:
    """Replace the tag list. Missing tags are created, as for posts."""
    db.execute(delete(ActivityTag).where(ActivityTag.activity_id == activity_id))
    db.flush()
    for tag_id in resolve_tags(db, org_id, names):
        db.add(ActivityTag(activity_id=activity_id, tag_id=tag_id))
    db.flush()


def tags_by_activity(
    db: Session, activity_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    """Tag names of many activities in one query, in name order."""
    tags: dict[uuid.UUID, list[str]] = defaultdict(list)
    if not activity_ids:
        return tags
    for activity_id, name in db.execute(
        select(ActivityTag.activity_id, Tag.name)
        .join(Tag, Tag.id == ActivityTag.tag_id)
        .where(ActivityTag.activity_id.in_(activity_ids), Tag.deleted_at.is_(None))
        .order_by(Tag.name)
    ):
        tags[activity_id].append(name)
    return tags


def with_activity_tag(query: Select[Any], tag: str | None) -> Select[Any]:
    """Only activities carrying a tag, given as a slug or a name as typed.

    A tag without letters or digits matches nothing, never everything.
    """
    if tag is None:
        return query
    slug = tag_slug(tag)
    if slug is None:
        return query.where(false())
    tagged = (
        select(ActivityTag.activity_id)
        .join(Tag, Tag.id == ActivityTag.tag_id)
        .where(Tag.slug == slug, Tag.deleted_at.is_(None))
    )
    return query.where(Activity.id.in_(tagged))


def suggest_activity_tags(
    db: Session, org: Organization, user_id: uuid.UUID, query: str, limit: int
) -> list[tuple[str, str, int]]:
    """Tags of the organization's activities for the activity form, most used first.

    Only managers write activities, and they see drafts too, so every live activity
    counts. Deleted activities do not.
    """
    if not get_access(db, org, user_id).has_any("activities"):
        raise api_error(status.HTTP_403_FORBIDDEN, "organization_forbidden")
    count = func.count(Activity.id)
    statement = (
        select(Tag.name, Tag.slug, count)
        .join(ActivityTag, ActivityTag.tag_id == Tag.id)
        .join(Activity, Activity.id == ActivityTag.activity_id)
        .where(
            Tag.org_id == org.id,
            Tag.deleted_at.is_(None),
            Activity.org_id == org.id,
            Activity.deleted_at.is_(None),
        )
    )
    if query.strip():
        prefix = tag_slug(query)
        if prefix is None:
            return []
        starts, inner = tag_word_patterns(prefix)
        statement = statement.where(or_(Tag.slug.like(starts), Tag.slug.like(inner)))
    rows = db.execute(
        statement.group_by(Tag.id).order_by(count.desc(), Tag.slug).limit(limit)
    ).all()
    return [(name, slug, total) for name, slug, total in rows]
