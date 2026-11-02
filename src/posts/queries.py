"""Lists of posts, newest first. The cursor is the post ID, which is time ordered (UUIDv7)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from src.models.organizations import Organization
from src.models.posts import OrgPost, PostTag
from src.models.tags import Tag
from src.organizations.service import live_organization
from src.posts.rules import POST_ACTIVE, POST_DRAFT, TRENDING_DAYS, TRENDING_LIMIT
from src.posts.visibility import member_org_ids, published_posts, visible_to


def next_page_cursor(rows: list[OrgPost], limit: int) -> uuid.UUID | None:
    """Rows arrive with one extra row, which only says whether another page exists."""
    if len(rows) <= limit:
        return None
    return rows[limit - 1].post_id


def _page(
    db: Session, query: Select, before: uuid.UUID | None, limit: int
) -> list[OrgPost]:
    if before is not None:
        query = query.where(OrgPost.post_id < before)
    rows = db.scalars(query.order_by(OrgPost.post_id.desc()).limit(limit + 1))
    return list(rows)


def org_timeline(
    db: Session,
    org_id: uuid.UUID,
    viewer_id: uuid.UUID | None,
    *,
    before: uuid.UUID | None,
    limit: int,
    kind: str | None,
    pinned_only: bool,
) -> list[OrgPost]:
    query = published_posts(viewer_id).where(OrgPost.org_id == org_id)
    if kind is not None:
        query = query.where(OrgPost.kind == kind)
    if pinned_only:
        query = query.where(OrgPost.pinned_at.is_not(None))
    return _page(db, query, before, limit)


def member_feed(
    db: Session, viewer_id: uuid.UUID, *, before: uuid.UUID | None, limit: int
) -> list[OrgPost]:
    """Posts from every organization the viewer belongs to."""
    query = published_posts(viewer_id).where(
        OrgPost.org_id.in_(member_org_ids(viewer_id))
    )
    return _page(db, query, before, limit)


def public_feed(db: Session, *, before: uuid.UUID | None, limit: int) -> list[OrgPost]:
    """Public posts from every organization, the same for visitors and members."""
    return _page(db, published_posts(None), before, limit)


def my_drafts(
    db: Session,
    org_id: uuid.UUID,
    author_id: uuid.UUID,
    *,
    before: uuid.UUID | None,
    limit: int,
) -> list[OrgPost]:
    query = select(OrgPost).where(
        OrgPost.org_id == org_id,
        OrgPost.author_id == author_id,
        OrgPost.status == POST_DRAFT,
        OrgPost.deleted_at.is_(None),
    )
    return _page(db, query, before, limit)


def popular_tags(db: Session, viewer_id: uuid.UUID | None) -> list[tuple[str, int]]:
    """Tags on the most visible posts published in the last few weeks."""
    since = datetime.now(UTC) - timedelta(days=TRENDING_DAYS)
    count = func.count(func.distinct(OrgPost.post_id))
    rows = db.execute(
        select(Tag.slug, func.min(Tag.name), count)
        .join(PostTag, PostTag.tag_id == Tag.id)
        .join(OrgPost, OrgPost.post_id == PostTag.post_id)
        .join(Organization, Organization.id == OrgPost.org_id)
        .where(
            Tag.deleted_at.is_(None),
            OrgPost.status == POST_ACTIVE,
            OrgPost.deleted_at.is_(None),
            OrgPost.published_at >= since,
            *live_organization(),
            visible_to(viewer_id),
        )
        .group_by(Tag.slug)
        .order_by(count.desc(), Tag.slug)
        .limit(TRENDING_LIMIT)
    ).all()
    return [(name, total) for _slug, name, total in rows]
