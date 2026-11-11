"""Routes for the post trash: list, restore, and remove for good."""

from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from src.auth.deps import CurrentPrincipal, Db
from src.organizations.access import get_access
from src.organizations.service import load_organization
from src.posts import trash
from src.posts.rules import may_purge, purge_at
from src.posts.schemas import PostResponse, TrashPage, TrashPost
from src.posts.views import to_responses
from src.validation import Uuid7

router = APIRouter(tags=["posts"])

Slug = Annotated[str, Path(pattern=r"^[A-Za-z0-9-]{1,80}$")]
Limit = Annotated[int, Query(ge=1, le=50)]


@router.get("/organizations/{slug}/post-trash")
def post_trash(
    slug: Slug,
    principal: CurrentPrincipal,
    db: Db,
    before: Annotated[Uuid7 | None, Query()] = None,
    limit: Limit = 20,
) -> TrashPage:
    org = load_organization(db, slug)
    rows = trash.list_trash(db, org, principal.user.id, before=before, limit=limit)
    can_purge = may_purge(get_access(db, org, principal.user.id))
    items = [
        TrashPost(
            id=post.post_id,
            kind=post.kind,
            visibility=post.visibility,
            title=post.title or "",
            deleted_at=post.deleted_at,
            purge_at=purge_at(post.deleted_at),
            deleted_by_name=name,
            can_purge=can_purge,
        )
        for post, name in rows[:limit]
        if post.deleted_at is not None
    ]
    next_before = rows[limit - 1][0].post_id if len(rows) > limit else None
    return TrashPage(items=items, next_before=next_before)


@router.post("/posts/{post_id}/restore")
def restore_post(post_id: Uuid7, principal: CurrentPrincipal, db: Db) -> PostResponse:
    post = trash.restore_post(db, post_id, principal.user.id)
    return to_responses(db, [post], principal.user.id)[0]


@router.delete("/posts/{post_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
def purge_post(post_id: Uuid7, principal: CurrentPrincipal, db: Db) -> None:
    trash.purge_post(db, post_id, principal.user.id)
