"""Pydantic DTOs for the org board (validation lives here)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from orgs.schemas import PublicOrgPostItem
from posts.blocks import MAX_BLOCKS, Block, has_content

PostKind = Literal["announcement", "discussion"]
PostStatus = Literal["published", "draft"]


def _trim(value: str) -> str:
    return value.strip()


class CreatePostRequest(BaseModel):
    """New board post or article draft.

    `blocks` is the long-form article body; legacy clients may still send
    a plain `body` plus image `media_ids`. Published posts need content,
    published announcements need a title; drafts only need something.
    """

    kind: PostKind = "discussion"
    status: PostStatus = "published"
    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=5000)
    blocks: list[Block] = Field(default_factory=list, max_length=MAX_BLOCKS)
    cover_media_id: UUID | None = None
    media_ids: list[UUID] = Field(default_factory=list, max_length=4)

    _body = field_validator("body", mode="before")(_trim)  # noqa: SLF001
    _title = field_validator("title", mode="before")(_trim)  # noqa: SLF001

    @model_validator(mode="after")
    def _content_rules(self) -> CreatePostRequest:
        filled = bool(self.body) or has_content(self.blocks)
        if self.status == "published":
            if not filled:
                raise ValueError("Post content is required.")
            if self.kind == "announcement" and not self.title:
                raise ValueError("Announcements require a title.")
        elif not (filled or self.title or self.cover_media_id):
            raise ValueError("Draft is empty.")
        return self


class UpdatePostRequest(BaseModel):
    """Author edits the article.

    Omitting `blocks` keeps the legacy title/body-only edit. Sending
    `blocks` replaces the article body; `cover_media_id` is only touched
    when present in the payload. `kind` may change while still a draft.
    """

    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=5000)
    blocks: list[Block] | None = Field(default=None, max_length=MAX_BLOCKS)
    cover_media_id: UUID | None = None
    kind: PostKind | None = None

    _body = field_validator("body", mode="before")(_trim)  # noqa: SLF001
    _title = field_validator("title", mode="before")(_trim)  # noqa: SLF001

    @model_validator(mode="after")
    def _legacy_body_required(self) -> UpdatePostRequest:
        if self.blocks is None and not self.body:
            raise ValueError("Post content is required.")
        return self

    @property
    def touches_cover(self) -> bool:
        return "cover_media_id" in self.model_fields_set


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
    status: PostStatus = "published"
    title: str
    body: str
    blocks: list[dict[str, Any]] = []
    cover_media_id: UUID | None = None
    revision_of: UUID | None = None
    pinned_at: datetime | None = None
    edited_at: datetime | None = None
    published_at: datetime | None = None
    deleted_at: datetime | None = None
    media: list[PostMediaResponse] = []
    comment_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PostPageResponse(BaseModel):
    """Numbered page; page 1 also carries the pinned rail for the header."""

    items: list[PostResponse]
    pinned: list[PostResponse] = []
    total: int = 0
    viewer_role: str = "member"
    viewer_permissions: list[str] = []


class PublicAnnouncementPage(BaseModel):
    """Guest-facing numbered page of announcement teasers (no auth)."""

    items: list[PublicOrgPostItem]
    total: int = 0


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
