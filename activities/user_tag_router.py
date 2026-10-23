"""Personal tag catalog: a name with no org, attached later on a post."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Response

from activities.tag_schemas import (
    TAG_SLUG,
    TagNameBody,
    UserTagItem,
    UserTagPostItem,
)
from activities.user_tag_service import UserTagPost, UserTagService, UserTagView
from core.dependencies import CurrentUser, get_current_user
from core.dependencies_tags import get_user_tag_service

router = APIRouter(tags=["tags"])


def _post(row: UserTagPost) -> UserTagPostItem:
    return UserTagPostItem(
        post_id=row.post_id,
        org_id=row.org_id,
        title=row.title,
        draft=row.draft,
        cover_url=row.cover_url,
    )


def _item(row: UserTagView) -> UserTagItem:
    return UserTagItem(
        name=row.name,
        slug=row.slug,
        post_count=row.post_count,
        created_at=row.created_at,
        posts=[_post(post) for post in row.posts],
    )


@router.get("/me/tags", response_model=list[UserTagItem])
def list_my_tags(
    current: CurrentUser = Depends(get_current_user),
    service: UserTagService = Depends(get_user_tag_service),
) -> list[UserTagItem]:
    """Tags the caller created. None of them belong to an org."""
    return [_item(row) for row in service.list_tags(current.id)]


@router.post("/me/tags", response_model=UserTagItem, status_code=201)
def create_my_tag(
    body: TagNameBody,
    current: CurrentUser = Depends(get_current_user),
    service: UserTagService = Depends(get_user_tag_service),
) -> UserTagItem:
    """Store a name. Attaching it to a post happens on the board."""
    return _item(service.create(current.id, body.name))


@router.get("/me/tags/{slug}/posts", response_model=list[UserTagPostItem])
def list_my_tag_posts(
    slug: str = Path(pattern=TAG_SLUG),
    current: CurrentUser = Depends(get_current_user),
    service: UserTagService = Depends(get_user_tag_service),
) -> list[UserTagPostItem]:
    """Posts that currently carry this tag, newest first."""
    return [_post(row) for row in service.list_posts(current.id, slug)]


@router.patch("/me/tags/{slug}", response_model=UserTagItem)
def rename_my_tag(
    body: TagNameBody,
    slug: str = Path(pattern=TAG_SLUG),
    current: CurrentUser = Depends(get_current_user),
    service: UserTagService = Depends(get_user_tag_service),
) -> UserTagItem:
    """Rename the tag and the same name on the caller's posts."""
    return _item(service.rename(current.id, slug, body.name))


@router.delete("/me/tags/{slug}", status_code=204)
def delete_my_tag(
    slug: str = Path(pattern=TAG_SLUG),
    current: CurrentUser = Depends(get_current_user),
    service: UserTagService = Depends(get_user_tag_service),
) -> Response:
    """Drop the tag and detach it from the caller's posts."""
    service.delete(current.id, slug)
    return Response(status_code=204)
