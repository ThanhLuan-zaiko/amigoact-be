"""View dataclasses returned by the board services (no FastAPI here)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class PostMediaBrief:
    """One attachment projected for the API response."""

    asset_id: UUID
    file_url: str
    mime: str


@dataclass(frozen=True)
class PostSnapshot:
    """Post row joined with author, attachments and comment total.

    status is the public publish state ("published" | "draft").
    """

    post_id: UUID
    org_id: UUID
    author_id: UUID
    author_name: str
    kind: str
    title: str
    body: str
    pinned_at: datetime | None
    edited_at: datetime | None
    media: list[PostMediaBrief] = field(default_factory=list)
    comment_count: int = 0
    created_at: datetime | None = None
    status: str = "published"
    blocks: list[dict[str, Any]] = field(default_factory=list)
    cover_media_id: UUID | None = None
    revision_of: UUID | None = None
    published_at: datetime | None = None
    deleted_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class PostContent:
    """Validated article payload handed from the router to the service."""

    title: str
    body: str
    blocks: list[Any] | None = None
    cover_media_id: UUID | None = None
    touch_cover: bool = True
    kind: str | None = None


@dataclass(frozen=True)
class PostPage:
    """One numbered board page plus the caller's org capabilities."""

    items: list[PostSnapshot]
    pinned: list[PostSnapshot]
    total: int
    viewer_role: str
    viewer_permissions: list[str]


@dataclass(frozen=True)
class TimelineOrg:
    """Public org card fields embedded in one timeline item."""

    id: UUID
    name: str
    slug: str
    logo_url: str | None


@dataclass(frozen=True)
class TimelineItem:
    """One public announcement teaser plus its org attribution."""

    id: UUID
    title: str
    excerpt: str
    cover_url: str | None
    author_name: str
    published_at: datetime | None
    comment_count: int
    org: TimelineOrg


@dataclass(frozen=True)
class TimelinePage:
    """Cursor page of the public announcement timeline."""

    items: list[TimelineItem]
    next_cursor: str | None


@dataclass(frozen=True)
class CommentSnapshot:
    """One comment row joined with its author display name."""

    comment_id: UUID
    post_id: UUID
    author_id: UUID
    author_name: str
    body: str
    created_at: datetime | None


@dataclass(frozen=True)
class CommentPage:
    items: list[CommentSnapshot]
    next_cursor: str | None
