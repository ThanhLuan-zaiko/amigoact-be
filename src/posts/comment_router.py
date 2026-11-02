"""Routes for comments on posts."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from src.auth.deps import CurrentPrincipal, Db, OptionalPrincipal
from src.auth.errors import api_error
from src.models.posts import PostComment
from src.organizations.access import get_access
from src.posts import comments
from src.posts.schemas import CommentCreate, CommentPage, CommentResponse
from src.posts.visibility import load_live_org, load_visible_post
from src.validation import Uuid7

router = APIRouter(tags=["posts"])

Limit = Annotated[int, Query(ge=1, le=100)]


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
    manager = False
    if viewer_id is not None:
        org = load_live_org(db, post.org_id)
        manager = get_access(db, org, viewer_id).can_manage
    items = [
        CommentResponse(
            id=comment.comment_id,
            body=comment.body,
            author_name=name,
            can_delete=viewer_id is not None
            and (comment.author_id == viewer_id or manager),
            created_at=comment.created_at,
        )
        for comment, name in rows[:limit]
    ]
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
    return CommentResponse(
        id=comment.comment_id,
        body=comment.body,
        author_name=principal.user.full_name,
        can_delete=True,
        created_at=comment.created_at,
    )


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(comment_id: Uuid7, principal: CurrentPrincipal, db: Db) -> None:
    comment = db.get(PostComment, comment_id)
    if comment is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "comment_not_found")
    post = load_visible_post(db, comment.post_id, principal.user.id)
    comments.delete_comment(
        db, comment, load_live_org(db, post.org_id), principal.user.id
    )
