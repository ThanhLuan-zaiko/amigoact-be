"""HTTP layer for article publish state, revisions and trash restore."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status

from core.config import Settings, get_settings
from core.dependencies import CurrentUser, get_current_user
from core.dependencies_workspace import get_post_lifecycle_service
from posts.lifecycle_service import PostLifecycleService
from posts.mappers import rate_limit, to_post
from posts.schemas import PostResponse

router = APIRouter(tags=["posts"])


@router.post(
    "/orgs/{org_id}/posts/{post_id}/revisions",
    response_model=PostResponse,
    status_code=status.HTTP_200_OK,
)
def open_revision(
    org_id: UUID,
    post_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: PostLifecycleService = Depends(get_post_lifecycle_service),
    settings: Settings = Depends(get_settings),
) -> PostResponse:
    """Get or create the author's private revision of a live post."""
    rate_limit(settings, f"post_revise:{current_user.id}", 30)
    return to_post(
        service.get_or_create_revision(org_id, post_id, current_user.id)
    )


@router.post(
    "/orgs/{org_id}/posts/{post_id}/publish",
    response_model=PostResponse,
    status_code=status.HTTP_200_OK,
)
def publish_post(
    org_id: UUID,
    post_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: PostLifecycleService = Depends(get_post_lifecycle_service),
) -> PostResponse:
    """Author publishes a draft onto the board."""
    return to_post(service.publish(org_id, post_id, current_user.id))


@router.post(
    "/orgs/{org_id}/posts/{post_id}/unpublish",
    response_model=PostResponse,
    status_code=status.HTTP_200_OK,
)
def unpublish_post(
    org_id: UUID,
    post_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: PostLifecycleService = Depends(get_post_lifecycle_service),
) -> PostResponse:
    """Author moves a published post back into their drafts."""
    return to_post(service.unpublish(org_id, post_id, current_user.id))


@router.post(
    "/orgs/{org_id}/posts/{post_id}/restore",
    response_model=PostResponse,
    status_code=status.HTTP_200_OK,
)
def restore_post(
    org_id: UUID,
    post_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: PostLifecycleService = Depends(get_post_lifecycle_service),
) -> PostResponse:
    """Author or manager brings a post back from the trash."""
    return to_post(service.restore(org_id, post_id, current_user.id))
