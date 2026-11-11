"""Comments on a post. Comments are flat and listed oldest first.

A deleted comment keeps its row and its place in the thread, so replies still read in
order. A manager can bring it back. It goes for good with its post.
"""

import uuid
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.errors import api_error
from src.auth.rate_limit import enforce_rate_limit
from src.models.auth import User
from src.models.organizations import Organization
from src.models.posts import OrgPost, PostComment
from src.organizations.access import ACTIVE, get_access
from src.posts.rules import (
    COMMENT_LIMIT,
    POST_ACTIVE,
    POST_WINDOW,
    comment_editable,
    may_restore,
)


def _forbidden() -> Exception:
    return api_error(status.HTTP_403_FORBIDDEN, "comment_forbidden")


def _not_found() -> Exception:
    return api_error(status.HTTP_404_NOT_FOUND, "comment_not_found")


def list_comments(
    db: Session,
    post: OrgPost,
    *,
    after: uuid.UUID | None,
    limit: int,
) -> list[tuple[PostComment, str]]:
    query = (
        select(PostComment, User.full_name)
        .join(User, User.id == PostComment.author_id)
        .where(PostComment.post_id == post.post_id)
    )
    if after is not None:
        query = query.where(PostComment.comment_id > after)
    rows = db.execute(query.order_by(PostComment.comment_id).limit(limit + 1)).all()
    return [(comment, name) for comment, name in rows]


def add_comment(
    db: Session,
    post: OrgPost,
    org: Organization,
    user_id: uuid.UUID,
    body: str,
) -> PostComment:
    if get_access(db, org, user_id).status != ACTIVE:
        raise _forbidden()
    if post.status != POST_ACTIVE:
        raise api_error(status.HTTP_409_CONFLICT, "post_not_published")
    enforce_rate_limit(db, f"comment:{user_id}", COMMENT_LIMIT, POST_WINDOW)
    comment = PostComment(
        comment_id=uuid.uuid7(),
        post_id=post.post_id,
        author_id=user_id,
        body=body,
    )
    db.add(comment)
    db.commit()
    return comment


def edit_comment(
    db: Session, comment: PostComment, org: Organization, user_id: uuid.UUID, body: str
) -> PostComment:
    """Only the author, only while still a member, and only shortly after writing it."""
    if comment.deleted_at is not None:
        raise _not_found()
    if comment.author_id != user_id or get_access(db, org, user_id).status != ACTIVE:
        raise _forbidden()
    if not comment_editable(comment.created_at, datetime.now(UTC)):
        raise api_error(status.HTTP_409_CONFLICT, "comment_edit_expired")
    comment.body = body
    comment.edited_at = datetime.now(UTC)
    db.commit()
    return comment


def delete_comment(
    db: Session, comment: PostComment, org: Organization, user_id: uuid.UUID
) -> None:
    """The comment's author or a manager may hide it. The row stays for a restore."""
    if comment.deleted_at is not None:
        raise _not_found()
    if comment.author_id != user_id and not get_access(db, org, user_id).can_manage:
        raise _forbidden()
    comment.deleted_at = datetime.now(UTC)
    db.commit()


def restore_comment(
    db: Session, comment: PostComment, org: Organization, user_id: uuid.UUID
) -> PostComment:
    if not may_restore(get_access(db, org, user_id)):
        raise _forbidden()
    if comment.deleted_at is None:
        raise api_error(status.HTTP_409_CONFLICT, "comment_not_deleted")
    comment.deleted_at = None
    db.commit()
    return comment
