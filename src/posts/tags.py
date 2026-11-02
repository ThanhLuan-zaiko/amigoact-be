"""Tags on posts. A tag belongs to one organization and is created the first time it is used."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.models.posts import PostTag
from src.models.tags import Tag
from src.posts.rules import TAG_LIMIT, tag_slug
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
