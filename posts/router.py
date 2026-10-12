"""HTTP layer for the org board: thin routing over PostService."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from core.config import Settings, get_settings
from core.dependencies import CurrentUser, get_current_user
from core.dependencies_workspace import get_comment_service, get_post_service
from core.exceptions import TooManyRequestsError
from posts.comments_service import CommentService
from posts.dtos import CommentSnapshot, PostSnapshot
from posts.schemas import (
    CommentPageResponse,
    CommentResponse,
    CreateCommentRequest,
    CreatePostRequest,
    PostPageResponse,
    PostResponse,
    UpdatePostRequest,
)
from posts.service import PostService

logger = logging.getLogger("amigoact.posts")

router = APIRouter(tags=["posts"])


def _to_post(snapshot: PostSnapshot) -> PostResponse:
    return PostResponse(
        post_id=snapshot.post_id,
        org_id=snapshot.org_id,
        author_id=snapshot.author_id,
        author_name=snapshot.author_name,
        kind=snapshot.kind,  # type: ignore[arg-type]
        title=snapshot.title,
        body=snapshot.body,
        pinned_at=snapshot.pinned_at,
        edited_at=snapshot.edited_at,
        media=[
            {"asset_id": m.asset_id, "file_url": m.file_url, "mime": m.mime}
            for m in snapshot.media
        ],
        comment_count=snapshot.comment_count,
        created_at=snapshot.created_at,
    )


def _to_comment(snapshot: CommentSnapshot) -> CommentResponse:
    return CommentResponse(
        comment_id=snapshot.comment_id,
        post_id=snapshot.post_id,
        author_id=snapshot.author_id,
        author_name=snapshot.author_name,
        body=snapshot.body,
        created_at=snapshot.created_at,
    )


def _rate_limit(settings: Settings, bucket: str, max_hits: int) -> None:
    """Fixed-window counter; best-effort like the ws-ticket limiter."""
    try:
        from auth.repository import CqlRateLimiter

        hits = CqlRateLimiter(settings.scylla_keyspace).hit(bucket, 60)
        if hits > max_hits:
            raise TooManyRequestsError("Too many requests.")
    except TooManyRequestsError:
        raise
    except Exception as exc:
        logger.warning("post rate-limit unavailable: %s", exc)


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
    cursor: str | None = Query(None, max_length=80),
    kind: str | None = Query(None, max_length=20),
) -> PostPageResponse:
    """Newest-first board page; first page carries the pinned rail."""
    post_kind = kind if kind in ("announcement", "discussion") else None
    page = service.list_posts(
        org_id, current_user.id, limit=limit, cursor=cursor, kind=post_kind
    )
    return PostPageResponse(
        items=[_to_post(item) for item in page.items],
        pinned=[_to_post(item) for item in page.pinned],
        next_cursor=page.next_cursor,
        viewer_role=page.viewer_role,
        viewer_permissions=page.viewer_permissions,
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
    _rate_limit(settings, f"post_create:{current_user.id}", 30)
    return _to_post(
        service.create_post(
            org_id,
            current_user.id,
            body.kind,
            body.title,
            body.body,
            body.media_ids,
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
    """One post detail for members."""
    return _to_post(service.get_post(org_id, post_id, current_user.id))


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
    """Author edits title/body; the kind stays put."""
    return _to_post(
        service.update_post(
            org_id, post_id, current_user.id, body.title, body.body
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
    service: PostService = Depends(get_post_service),
) -> Response:
    """Author removes their post; managers (post:manage) remove any."""
    service.delete_post(org_id, post_id, current_user.id)
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
    return _to_post(
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
    return _to_post(
        service.set_pinned(org_id, post_id, current_user.id, False)
    )


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
        items=[_to_comment(item) for item in page.items],
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
    _rate_limit(settings, f"comment_create:{current_user.id}", 60)
    return _to_comment(
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
