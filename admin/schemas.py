"""Pydantic DTOs for the platform-admin HTTP contract."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AdminStatusResponse(BaseModel):
    """Whether the caller may see platform-admin surfaces."""

    is_admin: bool


class AdminOrgItem(BaseModel):
    """One row of the org verification queue."""

    id: UUID
    name: str
    slug: str
    kind: str
    status: str
    legal_status: str
    tax_code: str | None
    legal_rep_name: str | None
    owner_id: UUID
    owner_name: str
    owner_email: str
    verified_at: datetime | None
    created_at: datetime


class AdminOrgPage(BaseModel):
    """Queue slice plus the pending badge count."""

    items: list[AdminOrgItem]
    total: int


class RejectOrgRequest(BaseModel):
    """Optional rejection note surfaced to the org owner."""

    reason: str = Field(default="", max_length=500)


class AdminUserItem(BaseModel):
    """One platform administrator row."""

    user_id: UUID
    full_name: str
    email: str


class GrantAdminRequest(BaseModel):
    """Promote an account by email address."""

    email: str = Field(min_length=3, max_length=254)
