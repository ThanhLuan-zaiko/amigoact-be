"""Pydantic DTOs for orgs (validation lives here)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TAX_PATTERN = re.compile(r"^\d{10}(-\d{3})?$")
_CCCD_PATTERN = re.compile(r"^\d{12}$")

OrgKind = Literal["organization", "club", "group", "business"]


def validate_slug(value: str) -> str:
    """Public slug: lowercase kebab, 2-60 chars."""
    slug = value.strip().lower()
    if len(slug) < 2 or len(slug) > 60 or not _SLUG_PATTERN.match(slug):
        raise ValueError("Slug must be 2-60 lowercase letters, digits, dashes.")
    return slug


def validate_tax_code(value: str) -> str:
    """Vietnam MST: 10 digits, branch adds -XXX suffix."""
    code = value.strip()
    if not _TAX_PATTERN.match(code):
        raise ValueError("Tax code must be 10 digits or 10 digits plus -XXX.")
    if len(set(code.replace("-", ""))) == 1:
        raise ValueError("Tax code looks invalid.")
    return code


def validate_cccd(value: str) -> str:
    """Vietnam CCCD: 12 digits, rejects trivial fakes."""
    code = value.strip()
    if not _CCCD_PATTERN.match(code):
        raise ValueError("National ID must be 12 digits.")
    if len(set(code)) == 1:
        raise ValueError("National ID looks invalid.")
    return code


class CreateOrgRequest(BaseModel):
    """Create an org. Business kind requires tax plus legal representative."""

    name: Annotated[str, Field(min_length=2, max_length=100)]
    slug: str
    description: Annotated[str, Field(max_length=500)] = ""
    kind: OrgKind = "organization"
    tax_code: str | None = None
    legal_rep_name: Annotated[str, Field(min_length=2, max_length=100)] | None = None
    legal_rep_id: str | None = None
    legal_rep_position: Annotated[str, Field(min_length=2, max_length=100)] | None = (
        None
    )

    _slug = field_validator("slug", mode="before")(validate_slug)  # noqa: SLF001
    _tax = field_validator("tax_code", mode="before")(  # noqa: SLF001
        lambda v: validate_tax_code(v) if v not in (None, "") else v
    )
    _cccd = field_validator("legal_rep_id", mode="before")(  # noqa: SLF001
        lambda v: validate_cccd(v) if v not in (None, "") else v
    )

    @model_validator(mode="after")
    def _require_business_identity(self) -> CreateOrgRequest:
        if self.kind == "business" and not (
            self.tax_code and self.legal_rep_name and self.legal_rep_id
        ):
            raise ValueError("Business orgs require tax_code and legal representative.")
        return self


class OrgResponse(BaseModel):
    """Public org card for dashboards and listings."""

    id: UUID
    name: str
    slug: str
    description: str = ""
    kind: OrgKind
    member_count: int = 1
    event_count: int = 0
    owner_id: UUID | None = None
    tax_code: str | None = None
    legal_rep_name: str | None = None
    legal_rep_id: str | None = None
    legal_rep_position: str | None = None
    legal_status: str = "none"
    status: str = "active"
    deleted_at: datetime | None = None
    created_at: datetime


class UpdateOrgRequest(BaseModel):
    """Owner edits name and description (slug and kind stay frozen)."""

    name: Annotated[str, Field(min_length=2, max_length=100)]
    description: Annotated[str, Field(max_length=500)] = ""


class MediaResponse(BaseModel):
    """One gallery row: metadata plus the public file URL."""

    id: UUID
    org_id: UUID
    kind: str = "image"
    mime: str
    size_bytes: int = 0
    file_url: str
    created_at: datetime
