"""Snapshot -> response DTO mappers shared by the board routers."""

from __future__ import annotations

import logging

from core.config import Settings
from core.exceptions import TooManyRequestsError
from posts.dtos import CommentSnapshot, PostPage, PostSnapshot
from posts.schemas import (
    CommentResponse,
    PostMediaResponse,
    PostPageResponse,
    PostResponse,
)

logger = logging.getLogger("amigoact.posts")


def to_post(snapshot: PostSnapshot) -> PostResponse:
    return PostResponse(
        post_id=snapshot.post_id,
        org_id=snapshot.org_id,
        author_id=snapshot.author_id,
        author_name=snapshot.author_name,
        kind=snapshot.kind,  # type: ignore[arg-type]
        status=snapshot.status,  # type: ignore[arg-type]
        title=snapshot.title,
        body=snapshot.body,
        blocks=snapshot.blocks,
        cover_media_id=snapshot.cover_media_id,
        revision_of=snapshot.revision_of,
        pinned_at=snapshot.pinned_at,
        edited_at=snapshot.edited_at,
        published_at=snapshot.published_at,
        deleted_at=snapshot.deleted_at,
        media=[
            PostMediaResponse(
                asset_id=m.asset_id, file_url=m.file_url, mime=m.mime
            )
            for m in snapshot.media
        ],
        comment_count=snapshot.comment_count,
        created_at=snapshot.created_at,
        updated_at=snapshot.updated_at,
    )


def to_page(page: PostPage) -> PostPageResponse:
    return PostPageResponse(
        items=[to_post(item) for item in page.items],
        pinned=[to_post(item) for item in page.pinned],
        total=page.total,
        viewer_role=page.viewer_role,
        viewer_permissions=page.viewer_permissions,
    )


def to_comment(snapshot: CommentSnapshot) -> CommentResponse:
    return CommentResponse(
        comment_id=snapshot.comment_id,
        post_id=snapshot.post_id,
        author_id=snapshot.author_id,
        author_name=snapshot.author_name,
        body=snapshot.body,
        created_at=snapshot.created_at,
    )


def rate_limit(settings: Settings, bucket: str, max_hits: int) -> None:
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
