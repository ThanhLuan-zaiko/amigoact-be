"""Routes for the feeds shown on the home page, and the popular tags beside them."""

from typing import Annotated

from fastapi import APIRouter, Query

from src.auth.deps import CurrentPrincipal, Db, OptionalPrincipal
from src.posts import queries
from src.posts.rules import TAG_NAME_MAX, TRENDING_LIMIT
from src.posts.schemas import PostPage, TagCount, TagList
from src.posts.views import post_page
from src.validation import Uuid7

router = APIRouter(tags=["posts"])

Limit = Annotated[int, Query(ge=1, le=50)]
Before = Annotated[Uuid7 | None, Query()]
TagFilter = Annotated[str | None, Query(min_length=1, max_length=TAG_NAME_MAX)]


@router.get("/feed")
def member_feed(
    principal: CurrentPrincipal,
    db: Db,
    before: Before = None,
    limit: Limit = 20,
    tag: TagFilter = None,
) -> PostPage:
    rows = queries.member_feed(
        db, principal.user.id, before=before, limit=limit, tag=tag
    )
    return post_page(db, rows, limit, principal.user.id)


@router.get("/feed/public")
def public_feed(
    principal: OptionalPrincipal,
    db: Db,
    before: Before = None,
    limit: Limit = 20,
    tag: TagFilter = None,
) -> PostPage:
    viewer_id = principal.user.id if principal else None
    rows = queries.public_feed(db, before=before, limit=limit, tag=tag)
    return post_page(db, rows, limit, viewer_id)


@router.get("/feed/popular-tags")
def popular_tags(principal: OptionalPrincipal, db: Db) -> TagList:
    viewer_id = principal.user.id if principal else None
    rows = queries.popular_tags(db, viewer_id)
    return TagList(
        items=[
            TagCount(name=name, count=total) for name, total in rows[:TRENDING_LIMIT]
        ]
    )
