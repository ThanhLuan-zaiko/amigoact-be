"""Request and response bodies of the organization feed."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, StringConstraints

from src.organizations.schemas import StrictRequest
from src.posts.rules import MEDIA_LIMIT, TAG_LIMIT, TAG_NAME_MAX
from src.validation import StrictBool, Uuid7, has_letter, multi_line, single_line

PostKind = Literal["announcement", "discussion"]
Visibility = Literal["public", "members"]

PostTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
    AfterValidator(single_line),
    AfterValidator(has_letter),
]
PostBody = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=5000),
    AfterValidator(multi_line),
]
TagName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=TAG_NAME_MAX),
    AfterValidator(single_line),
]
CommentBody = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
    AfterValidator(multi_line),
]


class PostCreate(StrictRequest):
    kind: PostKind
    # Empty means the kind's default: public for announcements, members for discussions.
    visibility: Visibility | None = None
    title: PostTitle
    body: PostBody
    tags: list[TagName] = Field(default_factory=list, max_length=TAG_LIMIT)
    media_ids: list[Uuid7] = Field(default_factory=list, max_length=MEDIA_LIMIT)
    draft: StrictBool = False


class PostUpdate(StrictRequest):
    """Only the fields that are sent change. Sent tags or media replace the old list."""

    title: PostTitle | None = None
    body: PostBody | None = None
    visibility: Visibility | None = None
    tags: list[TagName] | None = Field(default=None, max_length=TAG_LIMIT)
    media_ids: list[Uuid7] | None = Field(default=None, max_length=MEDIA_LIMIT)


class CommentCreate(StrictRequest):
    body: CommentBody


class CommentUpdate(StrictRequest):
    body: CommentBody


class TagCount(BaseModel):
    name: str
    count: int


class TagList(BaseModel):
    items: list[TagCount]


class MediaItem(BaseModel):
    id: uuid.UUID
    url: str
    mime: str


class OrgRef(BaseModel):
    slug: str
    name: str


class PostViewer(BaseModel):
    """What the signed-in viewer may do with this post. All false for visitors."""

    can_edit: bool
    can_delete: bool
    can_pin: bool
    can_hide: bool = False
    can_comment: bool


class PostResponse(BaseModel):
    id: uuid.UUID
    kind: str
    visibility: str
    status: str
    title: str
    body: str
    tags: list[str]
    media: list[MediaItem]
    pinned: bool
    hidden: bool = False
    comment_count: int
    org: OrgRef
    viewer: PostViewer
    created_at: datetime
    published_at: datetime | None
    edited_at: datetime | None


class PostPage(BaseModel):
    items: list[PostResponse]
    next_before: uuid.UUID | None


class CommentResponse(BaseModel):
    """A deleted comment keeps its place in the thread with an empty body."""

    id: uuid.UUID
    body: str
    author_name: str
    deleted: bool = False
    can_edit: bool = False
    can_delete: bool
    can_restore: bool = False
    created_at: datetime
    edited_at: datetime | None = None


class CommentPage(BaseModel):
    items: list[CommentResponse]
    next_after: uuid.UUID | None


class TrashPost(BaseModel):
    """A post in the trash. The body is left out, the title is enough to choose."""

    id: uuid.UUID
    kind: str
    visibility: str
    title: str
    deleted_at: datetime
    purge_at: datetime
    deleted_by_name: str | None
    can_purge: bool


class TrashPage(BaseModel):
    items: list[TrashPost]
    next_before: uuid.UUID | None
