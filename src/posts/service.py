"""Creating, editing, publishing, pinning, and deleting posts."""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.auth.errors import api_error
from src.auth.rate_limit import enforce_rate_limit
from src.media import service as media_service
from src.models.media import MediaAsset
from src.models.organizations import Organization
from src.models.posts import OrgPost, PostMedia, PostTag
from src.organizations.access import get_access
from src.posts.rules import (
    MEMBERS,
    POST_ACTIVE,
    POST_CREATE_LIMIT,
    POST_DRAFT,
    POST_WINDOW,
    PUBLIC,
    default_visibility,
    may_post,
)
from src.posts.schemas import PostCreate, PostUpdate
from src.posts.tags import replace_post_tags, resolve_tags
from src.validation import validation_failure


def _forbidden() -> HTTPException:
    return api_error(status.HTTP_403_FORBIDDEN, "post_forbidden")


def _members_post_has_no_media() -> HTTPException:
    return validation_failure({"media_ids": "members_post_has_no_media"})


def _link_media(
    db: Session, post: OrgPost, asset_ids: list[uuid.UUID], user_id: uuid.UUID
) -> None:
    """Replace the picture and video list. Files stay private until the post is published."""
    db.execute(delete(PostMedia).where(PostMedia.post_id == post.post_id))
    db.flush()
    for position, asset_id in enumerate(dict.fromkeys(asset_ids)):
        media_service.owned_asset(db, asset_id, user_id, allow_video=True)
        db.add(PostMedia(post_id=post.post_id, asset_id=asset_id, position=position))
    db.flush()
    _publish_media(db, post)


def _publish_media(db: Session, post: OrgPost) -> None:
    """Pictures of a live public post become public. Pictures of other posts do not."""
    if post.status != POST_ACTIVE or post.visibility != PUBLIC:
        return
    for asset in db.scalars(
        select(MediaAsset)
        .join(PostMedia, PostMedia.asset_id == MediaAsset.asset_id)
        .where(PostMedia.post_id == post.post_id)
    ):
        media_service.publish_asset(asset)


def _media_ids(db: Session, post_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.scalars(select(PostMedia.asset_id).where(PostMedia.post_id == post_id))
    )


def create_post(
    db: Session, org: Organization, user_id: uuid.UUID, payload: PostCreate
) -> OrgPost:
    access = get_access(db, org, user_id)
    if not may_post(payload.kind, access):
        raise _forbidden()
    enforce_rate_limit(db, f"post-create:{user_id}", POST_CREATE_LIMIT, POST_WINDOW)
    visibility = payload.visibility or default_visibility(payload.kind)
    if visibility == MEMBERS and payload.media_ids:
        raise _members_post_has_no_media()
    now = datetime.now(UTC)
    post = OrgPost(
        post_id=uuid.uuid7(),
        org_id=org.id,
        author_id=user_id,
        kind=payload.kind,
        title=payload.title,
        body=payload.body,
        status=POST_DRAFT if payload.draft else POST_ACTIVE,
        visibility=visibility,
        published_at=None if payload.draft else now,
    )
    db.add(post)
    db.flush()
    for tag_id in resolve_tags(db, org.id, payload.tags):
        db.add(PostTag(post_id=post.post_id, tag_id=tag_id))
    _link_media(db, post, payload.media_ids, user_id)
    db.commit()
    return post


def update_post(
    db: Session, post: OrgPost, user_id: uuid.UUID, payload: PostUpdate
) -> OrgPost:
    if post.author_id != user_id:
        raise _forbidden()
    visibility = payload.visibility or post.visibility
    media_ids = (
        payload.media_ids
        if payload.media_ids is not None
        else _media_ids(db, post.post_id)
    )
    if visibility == MEMBERS and media_ids:
        raise _members_post_has_no_media()
    if payload.title is not None:
        post.title = payload.title
    if payload.body is not None:
        post.body = payload.body
    post.visibility = visibility
    post.edited_at = datetime.now(UTC)
    if payload.tags is not None:
        replace_post_tags(db, post.post_id, post.org_id, payload.tags)
    if payload.media_ids is not None:
        _link_media(db, post, payload.media_ids, user_id)
    else:
        _publish_media(db, post)
    db.commit()
    return post


def publish_post(
    db: Session, post: OrgPost, org: Organization, user_id: uuid.UUID
) -> OrgPost:
    if post.author_id != user_id:
        raise _forbidden()
    if post.status != POST_DRAFT:
        raise api_error(status.HTTP_409_CONFLICT, "post_not_draft")
    if not may_post(post.kind, get_access(db, org, user_id)):
        raise _forbidden()
    post.status = POST_ACTIVE
    post.published_at = datetime.now(UTC)
    _publish_media(db, post)
    db.commit()
    return post


def set_pinned(
    db: Session, post: OrgPost, org: Organization, user_id: uuid.UUID, pinned: bool
) -> None:
    if not get_access(db, org, user_id).can_manage:
        raise _forbidden()
    if post.status != POST_ACTIVE:
        raise api_error(status.HTTP_409_CONFLICT, "post_not_published")
    post.pinned_at = datetime.now(UTC) if pinned else None
    db.commit()


def delete_post(
    db: Session, post: OrgPost, org: Organization, user_id: uuid.UUID
) -> None:
    """A draft is removed for good. A published post goes to the trash.

    A draft was never seen by anyone but its author, so nothing needs keeping. A
    published post keeps its comments and can be restored by a manager.
    """
    if post.status == POST_DRAFT:
        if post.author_id != user_id:
            raise _forbidden()
        db.delete(post)
        db.commit()
        return
    if post.author_id != user_id and not get_access(db, org, user_id).can_manage:
        raise _forbidden()
    post.deleted_at = datetime.now(UTC)
    post.deleted_by = user_id
    post.pinned_at = None
    db.commit()
