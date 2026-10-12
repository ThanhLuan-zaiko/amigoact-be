"""View dataclasses returned by the board services (no FastAPI here)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class PostMediaBrief:
    """One attachment projected for the API response."""

    asset_id: UUID
    file_url: str
    mime: str


@dataclass(frozen=True)
class PostSnapshot:
    """Post row joined with author, attachments and comment total."""

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


@dataclass(frozen=True)
class PostPage:
    """One board page plus the caller's capabilities inside the org."""

    items: list[PostSnapshot]
    pinned: list[PostSnapshot]
    next_cursor: str | None
    viewer_role: str
    viewer_permissions: list[str]


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
