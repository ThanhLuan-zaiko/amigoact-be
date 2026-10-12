"""HTTP layer for post comment threads: thin routing over CommentService."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from core.config import Settings, get_settings
from core.dependencies import CurrentUser, get_current_user
from core.dependencies_workspace import get_comment_service
from posts.comments_service import CommentService
from posts.mappers import rate_limit, to_comment
from posts.schemas import (
    CommentPageResponse,
    CommentResponse,
    CreateCommentRequest,
)

router = APIRouter(tags=["posts"])


@router.get(
    "/orgs/{org_id}/posts/{post_id}/comments",
    response_model=CommentPageResponse,
    status_code=status.HTTP_200_OK,
)
def list_comments(
    org_id: UUID,
    post_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: CommentService = Depends(get_comment_service),
    limit: int = Query(20, ge=1, le=50),
    cursor: str | None = Query(None, max_length=80),
) -> CommentPageResponse:
    """Oldest-first comment thread of one post."""
    page = service.list_comments(
        org_id, post_id, current_user.id, limit=limit, cursor=cursor
    )
    return CommentPageResponse(
        items=[to_comment(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.post(
    "/orgs/{org_id}/posts/{post_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_comment(
    org_id: UUID,
    post_id: UUID,
    body: CreateCommentRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: CommentService = Depends(get_comment_service),
    settings: Settings = Depends(get_settings),
) -> CommentResponse:
    """Member comments on a live post."""
    rate_limit(settings, f"comment_create:{current_user.id}", 60)
    return to_comment(
        service.add_comment(org_id, post_id, current_user.id, body.body)
    )


@router.delete(
    "/orgs/{org_id}/posts/{post_id}/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def delete_comment(
    org_id: UUID,
    post_id: UUID,
    comment_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: CommentService = Depends(get_comment_service),
) -> Response:
    """Author removes their comment; managers remove any."""
    service.delete_comment(org_id, post_id, comment_id, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
