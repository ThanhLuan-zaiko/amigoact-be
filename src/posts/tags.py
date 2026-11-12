"""Tags on posts. A tag belongs to one organization and is created the first time it is used."""

import uuid

from fastapi import status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.auth.errors import api_error
from src.models.organizations import Organization
from src.models.posts import OrgPost, PostTag
from src.models.tags import Tag
from src.organizations.access import ACTIVE, get_access
from src.posts.rules import POST_ACTIVE, TAG_LIMIT, tag_slug, tag_word_patterns
from src.validation import validation_failure


def resolve_tags(db: Session, org_id: uuid.UUID, names: list[str]) -> list[uuid.UUID]:
    """Map names to tag IDs, creating missing tags. Two names with one slug count once."""
    by_slug: dict[str, str] = {}
    for name in names:
        slug = tag_slug(name)
        if slug is None:
            raise validation_failure({"tags": "tag_invalid"})
        by_slug.setdefault(slug, name)
    if len(by_slug) > TAG_LIMIT:
        raise validation_failure({"tags": "too_many_tags"})
    ids: list[uuid.UUID] = []
    for slug, name in by_slug.items():
        # ON CONFLICT keeps two people creating the same new tag at once from failing.
        db.execute(
            insert(Tag)
            .values(id=uuid.uuid7(), org_id=org_id, slug=slug, name=name)
            .on_conflict_do_nothing(index_elements=["org_id", "slug"])
        )
        tag_id = db.scalar(select(Tag.id).where(Tag.org_id == org_id, Tag.slug == slug))
        if tag_id is not None:
            ids.append(tag_id)
    return ids


def replace_post_tags(
    db: Session, post_id: uuid.UUID, org_id: uuid.UUID, names: list[str]
) -> None:
    db.execute(delete(PostTag).where(PostTag.post_id == post_id))
    db.flush()
    for tag_id in resolve_tags(db, org_id, names):
        db.add(PostTag(post_id=post_id, tag_id=tag_id))
    db.flush()


def suggest_tags(
    db: Session, org: Organization, user_id: uuid.UUID, query: str, limit: int
) -> list[tuple[str, str, int]]:
    """Tags of the organization for its members to pick, most used first.

    Only tags on live published posts count, so a tag that sits only on a draft
    or a deleted or hidden post is not shown. A query matches the start of any
    word of the slug, so "truong" finds "Moi truong".
    """
    if get_access(db, org, user_id).status != ACTIVE:
        raise api_error(status.HTTP_403_FORBIDDEN, "post_forbidden")
    count = func.count(OrgPost.post_id)
    statement = (
        select(Tag.name, Tag.slug, count)
        .join(PostTag, PostTag.tag_id == Tag.id)
        .join(OrgPost, OrgPost.post_id == PostTag.post_id)
        .where(
            Tag.org_id == org.id,
            Tag.deleted_at.is_(None),
            OrgPost.org_id == org.id,
            OrgPost.status == POST_ACTIVE,
            OrgPost.deleted_at.is_(None),
            OrgPost.hidden_at.is_(None),
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
