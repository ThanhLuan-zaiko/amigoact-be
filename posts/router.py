"""HTTP layer for the org board: thin routing over the post services.

Static sub-paths (/posts/drafts, /posts/trash) are declared before
/posts/{post_id} so the UUID path param never shadows them. Publish
state moves live in lifecycle_router.py, comments in comments_router.py.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from core.config import Settings, get_settings
from core.dependencies import CurrentUser, get_current_user
from core.dependencies_workspace import (
    get_post_lifecycle_service,
    get_post_service,
)
from posts.lifecycle_service import PostLifecycleService
from posts.mappers import rate_limit, to_page, to_post
from posts.schemas import (
    CreatePostRequest,
    PostPageResponse,
    PostResponse,
    UpdatePostRequest,
)
from posts.service import PostService

router = APIRouter(tags=["posts"])


@router.get(
    "/orgs/{org_id}/posts",
    response_model=PostPageResponse,
    status_code=status.HTTP_200_OK,
)
def list_posts(
    org_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: PostService = Depends(get_post_service),
    limit: int = Query(20, ge=1, le=50),
    page: int = Query(1, ge=1),
    kind: str | None = Query(None, max_length=20),
) -> PostPageResponse:
    """Newest-first numbered page; page 1 carries the pinned rail."""
    post_kind = kind if kind in ("announcement", "discussion") else None
    return to_page(
        service.list_posts(
            org_id, current_user.id, limit=limit, page=page,
            kind=post_kind,
        )
    )


@router.get(
    "/orgs/{org_id}/posts/drafts",
    response_model=PostPageResponse,
    status_code=status.HTTP_200_OK,
)
def list_drafts(
    org_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: PostLifecycleService = Depends(get_post_lifecycle_service),
    limit: int = Query(20, ge=1, le=50),
    page: int = Query(1, ge=1),
) -> PostPageResponse:
    """The caller's own unpublished drafts inside the org."""
    return to_page(
        service.list_drafts(
            org_id, current_user.id, limit=limit, page=page
        )
    )


@router.get(
    "/orgs/{org_id}/posts/trash",
    response_model=PostPageResponse,
    status_code=status.HTTP_200_OK,
)
def list_trash(
    org_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: PostLifecycleService = Depends(get_post_lifecycle_service),
    limit: int = Query(20, ge=1, le=50),
    page: int = Query(1, ge=1),
) -> PostPageResponse:
    """Soft-deleted posts: managers see all, authors their own."""
    return to_page(
        service.list_trash(
            org_id, current_user.id, limit=limit, page=page
        )
    )


@router.post(
    "/orgs/{org_id}/posts",
    response_model=PostResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_post(
    org_id: UUID,
    body: CreatePostRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: PostService = Depends(get_post_service),
    settings: Settings = Depends(get_settings),
) -> PostResponse:
    """Members post discussions; announcements need post:announce."""
    rate_limit(settings, f"post_create:{current_user.id}", 30)
    return to_post(
        service.create_post(
            org_id,
            current_user.id,
            body.kind,
            body.title,
            body.body,
            body.media_ids,
            blocks=body.blocks,
            cover_media_id=body.cover_media_id,
            status=body.status,
        )
    )


@router.get(
    "/orgs/{org_id}/posts/{post_id}",
    response_model=PostResponse,
    status_code=status.HTTP_200_OK,
)
def get_post(
    org_id: UUID,
    post_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: PostService = Depends(get_post_service),
) -> PostResponse:
    """One post detail for members (own drafts included)."""
    return to_post(service.get_post(org_id, post_id, current_user.id))


@router.patch(
    "/orgs/{org_id}/posts/{post_id}",
    response_model=PostResponse,
    status_code=status.HTTP_200_OK,
)
def update_post(
    org_id: UUID,
    post_id: UUID,
    body: UpdatePostRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: PostService = Depends(get_post_service),
) -> PostResponse:
    """Author edits the article; kind only changes while a draft."""
    return to_post(
        service.update_post(
            org_id,
            post_id,
            current_user.id,
            body.title,
            body.body,
            blocks=body.blocks,
            cover_media_id=body.cover_media_id,
            touch_cover=body.touches_cover,
            kind=body.kind,
        )
    )


@router.delete(
    "/orgs/{org_id}/posts/{post_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def delete_post(
    org_id: UUID,
    post_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: PostLifecycleService = Depends(get_post_lifecycle_service),
    hard: bool = Query(default=False),
) -> Response:
    """Soft delete to trash by default; hard=true erases it for good."""
    if hard:
        service.hard_delete(org_id, post_id, current_user.id)
    else:
        service.soft_delete(org_id, post_id, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/orgs/{org_id}/posts/{post_id}/pin",
    response_model=PostResponse,
    status_code=status.HTTP_200_OK,
)
def pin_post(
    org_id: UUID,
    post_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: PostService = Depends(get_post_service),
) -> PostResponse:
    """Manager pins a post onto the board rail."""
    return to_post(
        service.set_pinned(org_id, post_id, current_user.id, True)
    )


@router.post(
    "/orgs/{org_id}/posts/{post_id}/unpin",
    response_model=PostResponse,
    status_code=status.HTTP_200_OK,
)
def unpin_post(
    org_id: UUID,
    post_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: PostService = Depends(get_post_service),
) -> PostResponse:
    """Manager lifts a post off the pinned rail."""
    return to_post(
        service.set_pinned(org_id, post_id, current_user.id, False)
    )
