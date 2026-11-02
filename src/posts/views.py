"""Turning post rows into response bodies. Each list costs a fixed number of queries."""

import uuid
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.media import MediaAsset
from src.models.organizations import Organization
from src.models.posts import OrgPost, PostComment, PostMedia, PostTag
from src.models.tags import Tag
from src.organizations.access import ACTIVE, Access, get_access
from src.posts.queries import next_page_cursor
from src.posts.rules import POST_ACTIVE
from src.posts.schemas import (
    CommentResponse,
    MediaItem,
    OrgRef,
    PostPage,
    PostResponse,
    PostViewer,
)


def _viewer_access(
    db: Session, posts: list[OrgPost], viewer_id: uuid.UUID | None
) -> dict[uuid.UUID, Access]:
    if viewer_id is None:
        return {}
    orgs = db.scalars(
        select(Organization).where(Organization.id.in_({p.org_id for p in posts}))
    )
    return {org.id: get_access(db, org, viewer_id) for org in orgs}


def _viewer_flags(
    post: OrgPost, access: Access | None, viewer_id: uuid.UUID | None
) -> PostViewer:
    if viewer_id is None or access is None:
        return PostViewer(
            can_edit=False, can_delete=False, can_pin=False, can_comment=False
        )
    is_author = post.author_id == viewer_id
    is_live = post.status == POST_ACTIVE and post.deleted_at is None
    return PostViewer(
        can_edit=is_author,
        can_delete=is_author or access.can_manage,
        can_pin=access.can_manage and is_live,
        can_comment=access.status == ACTIVE and is_live,
    )


def to_responses(
    db: Session, posts: list[OrgPost], viewer_id: uuid.UUID | None
) -> list[PostResponse]:
    if not posts:
        return []
    ids = [post.post_id for post in posts]
    orgs = {
        org.id: org
        for org in db.scalars(
            select(Organization).where(Organization.id.in_({p.org_id for p in posts}))
        )
    }
    tags: dict[uuid.UUID, list[str]] = defaultdict(list)
    for post_id, name in db.execute(
        select(PostTag.post_id, Tag.name)
        .join(Tag, Tag.id == PostTag.tag_id)
        .where(PostTag.post_id.in_(ids))
        .order_by(Tag.name)
    ):
        tags[post_id].append(name)
    media: dict[uuid.UUID, list[MediaItem]] = defaultdict(list)
    for post_id, asset in db.execute(
        select(PostMedia.post_id, MediaAsset)
        .join(MediaAsset, MediaAsset.asset_id == PostMedia.asset_id)
        .where(PostMedia.post_id.in_(ids))
        .order_by(PostMedia.position)
    ):
        media[post_id].append(
            MediaItem(
                id=asset.asset_id,
                url=f"/media/{asset.asset_id}/file",
                mime=asset.mime or "application/octet-stream",
            )
        )
    comments = dict(
        db.execute(
            select(PostComment.post_id, func.count())
            .where(PostComment.post_id.in_(ids))
            .group_by(PostComment.post_id)
        ).all()
    )
    access = _viewer_access(db, posts, viewer_id)
    return [
        PostResponse(
            id=post.post_id,
            kind=post.kind,
            visibility=post.visibility,
            status=post.status,
            title=post.title or "",
            body=post.body or "",
            tags=tags[post.post_id],
            media=media[post.post_id],
            pinned=post.pinned_at is not None,
            comment_count=comments.get(post.post_id, 0),
            org=OrgRef(slug=orgs[post.org_id].slug, name=orgs[post.org_id].name),
            viewer=_viewer_flags(post, access.get(post.org_id), viewer_id),
            created_at=post.created_at,
            published_at=post.published_at,
            edited_at=post.edited_at,
        )
        for post in posts
    ]


def to_comment_responses(
    db: Session,
    post: OrgPost,
    rows: list[tuple[PostComment, str]],
    viewer_id: uuid.UUID | None,
) -> list[CommentResponse]:
    org = db.get(Organization, post.org_id)
    access = get_access(db, org, viewer_id) if (org and viewer_id) else None
    return [
        CommentResponse(
            id=comment.comment_id,
            body=comment.body,
            author_name=author_name,
            can_delete=viewer_id is not None
            and (
                comment.author_id == viewer_id
                or (access is not None and access.can_manage)
            ),
            created_at=comment.created_at,
        )
        for comment, author_name in rows
    ]


def post_page(
    db: Session, rows: list[OrgPost], limit: int, viewer_id: uuid.UUID | None
) -> PostPage:
    return PostPage(
        items=to_responses(db, rows[:limit], viewer_id),
        next_before=next_page_cursor(rows, limit),
    )
