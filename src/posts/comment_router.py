"""Routes for comments on posts."""

from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy.orm import Session

from src.auth.deps import CurrentPrincipal, Db, OptionalPrincipal
from src.auth.errors import api_error
from src.models.auth import User
from src.models.organizations import Organization
from src.models.posts import OrgPost, PostComment
from src.posts import comments
from src.posts.schemas import (
    CommentCreate,
    CommentPage,
    CommentResponse,
    CommentUpdate,
)
from src.posts.views import to_comment_responses
from src.posts.visibility import load_live_org, load_visible_post
from src.validation import Uuid7

router = APIRouter(tags=["posts"])

Limit = Annotated[int, Query(ge=1, le=100)]


def _load_comment(
    db: Session, comment_id: Uuid7, viewer_id: Uuid7
) -> tuple[PostComment, OrgPost, Organization]:
    """A comment on a post the viewer can see, or a 404 that hides it."""
    comment = db.get(PostComment, comment_id)
    if comment is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "comment_not_found")
    post = load_visible_post(db, comment.post_id, viewer_id)
    return comment, post, load_live_org(db, post.org_id)


def _one(
    db: Session, post: OrgPost, comment: PostComment, name: str, viewer_id: Uuid7
) -> CommentResponse:
    return to_comment_responses(db, post, [(comment, name)], viewer_id)[0]


@router.get("/posts/{post_id}/comments")
def list_comments(
    post_id: Uuid7,
    principal: OptionalPrincipal,
    db: Db,
    after: Annotated[Uuid7 | None, Query()] = None,
    limit: Limit = 50,
) -> CommentPage:
    viewer_id = principal.user.id if principal else None
    post = load_visible_post(db, post_id, viewer_id)
    rows = comments.list_comments(db, post, after=after, limit=limit)
    items = to_comment_responses(db, post, rows[:limit], viewer_id)
    next_after = rows[limit - 1][0].comment_id if len(rows) > limit else None
    return CommentPage(items=items, next_after=next_after)


@router.post("/posts/{post_id}/comments", status_code=status.HTTP_201_CREATED)
def add_comment(
    post_id: Uuid7, payload: CommentCreate, principal: CurrentPrincipal, db: Db
) -> CommentResponse:
    post = load_visible_post(db, post_id, principal.user.id)
    comment = comments.add_comment(
        db,
        post,
        load_live_org(db, post.org_id),
        principal.user.id,
        payload.body,
    )
    return _one(db, post, comment, principal.user.full_name, principal.user.id)


@router.patch("/comments/{comment_id}")
def edit_comment(
    comment_id: Uuid7, payload: CommentUpdate, principal: CurrentPrincipal, db: Db
) -> CommentResponse:
    comment, post, org = _load_comment(db, comment_id, principal.user.id)
    comment = comments.edit_comment(db, comment, org, principal.user.id, payload.body)
    return _one(db, post, comment, principal.user.full_name, principal.user.id)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(comment_id: Uuid7, principal: CurrentPrincipal, db: Db) -> None:
    comment, _post, org = _load_comment(db, comment_id, principal.user.id)
    comments.delete_comment(db, comment, org, principal.user.id)


@router.post("/comments/{comment_id}/restore")
def restore_comment(
    comment_id: Uuid7, principal: CurrentPrincipal, db: Db
) -> CommentResponse:
    comment, post, org = _load_comment(db, comment_id, principal.user.id)
    comment = comments.restore_comment(db, comment, org, principal.user.id)
    author = db.get(User, comment.author_id)
    name = author.full_name if author else ""
    return _one(db, post, comment, name, principal.user.id)
