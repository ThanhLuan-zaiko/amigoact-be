"""Pydantic DTOs for the org board (validation lives here)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

PostKind = Literal["announcement", "discussion"]


def _trim(value: str) -> str:
    return value.strip()


class CreatePostRequest(BaseModel):
    """New board post; announcements must carry a title."""

    kind: PostKind = "discussion"
    title: str = Field(default="", max_length=200)
    body: str = Field(min_length=1, max_length=5000)
    media_ids: list[UUID] = Field(default_factory=list, max_length=4)

    _body = field_validator("body", mode="before")(_trim)  # noqa: SLF001
    _title = field_validator("title", mode="before")(_trim)  # noqa: SLF001

    @field_validator("title")
    @classmethod
    def _announcement_needs_title(cls, value: str, info) -> str:  # noqa: ANN001, ANN206
        if info.data.get("kind") == "announcement" and not value:
            raise ValueError("Announcements require a title.")
        return value


class UpdatePostRequest(BaseModel):
    """Author edits title/body; kind and attachments stay put."""

    title: str = Field(default="", max_length=200)
    body: str = Field(min_length=1, max_length=5000)

    _body = field_validator("body", mode="before")(_trim)  # noqa: SLF001
    _title = field_validator("title", mode="before")(_trim)  # noqa: SLF001


class CreateCommentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=2000)

    _body = field_validator("body", mode="before")(_trim)  # noqa: SLF001


class PostMediaResponse(BaseModel):
    asset_id: UUID
    file_url: str
    mime: str


class PostResponse(BaseModel):
    post_id: UUID
    org_id: UUID
    author_id: UUID
    author_name: str
    kind: PostKind
    title: str
    body: str
    pinned_at: datetime | None = None
    edited_at: datetime | None = None
    media: list[PostMediaResponse] = []
    comment_count: int = 0
    created_at: datetime | None = None


class PostPageResponse(BaseModel):
    """First page also carries the pinned rail for the board header."""

    items: list[PostResponse]
    pinned: list[PostResponse] = []
    next_cursor: str | None = None
    viewer_role: str = "member"
    viewer_permissions: list[str] = []


class CommentResponse(BaseModel):
    comment_id: UUID
    post_id: UUID
    author_id: UUID
    author_name: str
    body: str
    created_at: datetime | None = None


class CommentPageResponse(BaseModel):
    items: list[CommentResponse]
    next_cursor: str | None = None
