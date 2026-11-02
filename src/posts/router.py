"""Routes for posts: writing them, reading an organization's feed, and managing one post."""

from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from src.auth.deps import CurrentPrincipal, Db, OptionalPrincipal
from src.organizations.service import load_organization
from src.posts import queries, service
from src.posts.schemas import PostCreate, PostPage, PostResponse, PostUpdate
from src.posts.views import post_page, to_responses
from src.posts.visibility import load_live_org, load_visible_post
from src.validation import Uuid7

router = APIRouter(tags=["posts"])

Slug = Annotated[str, Path(pattern=r"^[A-Za-z0-9-]{1,80}$")]
Limit = Annotated[int, Query(ge=1, le=50)]
Before = Annotated[Uuid7 | None, Query()]


@router.post("/organizations/{slug}/posts", status_code=status.HTTP_201_CREATED)
def create_post(
    slug: Slug, payload: PostCreate, principal: CurrentPrincipal, db: Db
) -> PostResponse:
    org = load_organization(db, slug)
    post = service.create_post(db, org, principal.user.id, payload)
    return to_responses(db, [post], principal.user.id)[0]


@router.get("/organizations/{slug}/posts")
def org_posts(
    slug: Slug,
    principal: OptionalPrincipal,
    db: Db,
    before: Before = None,
    limit: Limit = 20,
    kind: Annotated[str | None, Query(pattern="^(announcement|discussion)$")] = None,
    pinned_only: bool = False,
) -> PostPage:
    org = load_organization(db, slug)
    viewer_id = principal.user.id if principal else None
    rows = queries.org_timeline(
        db,
        org.id,
        viewer_id,
        before=before,
        limit=limit,
        kind=kind,
        pinned_only=pinned_only,
    )
    return post_page(db, rows, limit, viewer_id)


@router.get("/organizations/{slug}/post-drafts")
def my_drafts(
    slug: Slug,
    principal: CurrentPrincipal,
    db: Db,
    before: Before = None,
    limit: Limit = 20,
) -> PostPage:
    org = load_organization(db, slug)
    rows = queries.my_drafts(db, org.id, principal.user.id, before=before, limit=limit)
    return post_page(db, rows, limit, principal.user.id)


@router.get("/posts/{post_id}")
def get_post(post_id: Uuid7, principal: OptionalPrincipal, db: Db) -> PostResponse:
    viewer_id = principal.user.id if principal else None
    post = load_visible_post(db, post_id, viewer_id)
    return to_responses(db, [post], viewer_id)[0]


@router.patch("/posts/{post_id}")
def update_post(
    post_id: Uuid7, payload: PostUpdate, principal: CurrentPrincipal, db: Db
) -> PostResponse:
    post = load_visible_post(db, post_id, principal.user.id)
    post = service.update_post(db, post, principal.user.id, payload)
    return to_responses(db, [post], principal.user.id)[0]


@router.post("/posts/{post_id}/publish")
def publish_post(post_id: Uuid7, principal: CurrentPrincipal, db: Db) -> PostResponse:
    post = load_visible_post(db, post_id, principal.user.id)
    org = load_live_org(db, post.org_id)
    post = service.publish_post(db, post, org, principal.user.id)
    return to_responses(db, [post], principal.user.id)[0]


@router.post("/posts/{post_id}/pin", status_code=status.HTTP_204_NO_CONTENT)
def pin_post(post_id: Uuid7, principal: CurrentPrincipal, db: Db) -> None:
    post = load_visible_post(db, post_id, principal.user.id)
    service.set_pinned(
        db, post, load_live_org(db, post.org_id), principal.user.id, True
    )


@router.post("/posts/{post_id}/unpin", status_code=status.HTTP_204_NO_CONTENT)
def unpin_post(post_id: Uuid7, principal: CurrentPrincipal, db: Db) -> None:
    post = load_visible_post(db, post_id, principal.user.id)
    service.set_pinned(
        db, post, load_live_org(db, post.org_id), principal.user.id, False
    )


@router.delete("/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(post_id: Uuid7, principal: CurrentPrincipal, db: Db) -> None:
    post = load_visible_post(db, post_id, principal.user.id)
    service.delete_post(db, post, load_live_org(db, post.org_id), principal.user.id)
