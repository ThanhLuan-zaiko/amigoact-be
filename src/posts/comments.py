"""Comments on a post. Comments are flat and listed oldest first."""

import uuid

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.errors import api_error
from src.auth.rate_limit import enforce_rate_limit
from src.models.auth import User
from src.models.organizations import Organization
from src.models.posts import OrgPost, PostComment
from src.organizations.access import ACTIVE, get_access
from src.posts.rules import COMMENT_LIMIT, POST_ACTIVE, POST_WINDOW


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
        raise api_error(status.HTTP_403_FORBIDDEN, "comment_forbidden")
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


def delete_comment(
    db: Session, comment: PostComment, org: Organization, user_id: uuid.UUID
) -> None:
    """The comment's author or a manager of the organization may delete it."""
    if comment.author_id != user_id and not get_access(db, org, user_id).can_manage:
        raise api_error(status.HTTP_403_FORBIDDEN, "comment_forbidden")
    db.delete(comment)
    db.commit()
