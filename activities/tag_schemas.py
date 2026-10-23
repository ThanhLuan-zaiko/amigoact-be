"""Pydantic DTOs for the org-scoped tag HTTP contract."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from activities.model import tag_slug

TAG_SLUG = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


class TagNameBody(BaseModel):
    """Display name payload for create/rename."""

    name: str = Field(min_length=1, max_length=40)

    @field_validator("name")
    @classmethod
    def _name_slugs(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped or not tag_slug(stripped):
            raise ValueError("name must contain letters or digits")
        return stripped


class TagMergeBody(BaseModel):
    """Merge target: the slug of the tag that survives."""

    into: str = Field(pattern=TAG_SLUG, max_length=80)


class OrgTagItem(BaseModel):
    """One org catalog row with its live activity count."""

    id: UUID
    name: str
    slug: str
    activity_count: int
    post_count: int = 0
    created_at: datetime
    deleted_at: datetime | None = None


class OrgTagPage(BaseModel):
    """Tag listing plus capability flag and the trash badge."""

    items: list[OrgTagItem]
    can_manage: bool
    trash_count: int = 0


class PublicTagItem(BaseModel):
    """Cross-org suggestion: no id, one slug maps to many org tags."""

    name: str
    slug: str


class OwnedTagItem(BaseModel):
    """A tag from another org the caller owns, offered as a copy."""

    name: str
    slug: str
    org_id: UUID
    org_name: str


class UserTagPostItem(BaseModel):
    """A post that carries one of the caller's tags."""

    post_id: UUID
    org_id: UUID
    title: str
    draft: bool = False
    cover_url: str | None = None


class UserTagItem(BaseModel):
    """One tag in the signed-in user's catalog."""

    name: str
    slug: str
    post_count: int = 0
    created_at: datetime
    posts: list[UserTagPostItem] = []
