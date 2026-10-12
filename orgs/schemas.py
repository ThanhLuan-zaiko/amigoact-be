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
_EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ORG_PHONE = re.compile(r"^[0-9+\-().\s]{5,20}$")
_WEBSITE_SHAPE = re.compile(
    r"^(https?://)?[a-z0-9][a-z0-9.-]*\.[a-z]{2,}(/[^\s]*)?$", re.IGNORECASE
)

OrgKind = Literal["organization", "club", "group", "business"]
MediaRole = Literal["gallery", "cover", "logo", "attachment"]
OrgSort = Literal["newest", "name", "members"]
JoinPolicy = Literal["invite", "open"]


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


def validate_contact_email(value: str) -> str:
    """Org inbox address: optional, plain email shape."""
    address = value.strip().lower()
    if len(address) > 254 or not _EMAIL_SHAPE.match(address):
        raise ValueError("Contact email is invalid.")
    return address


def validate_org_phone(value: str) -> str:
    """Org hotline: digits plus dialing punctuation, 5-20 chars."""
    phone = value.strip()
    if not _ORG_PHONE.match(phone):
        raise ValueError("Contact phone is invalid.")
    return phone


def validate_website(value: str) -> str:
    """Org site: bare domain or http(s) URL without spaces."""
    site = value.strip()
    if len(site) > 255 or not _WEBSITE_SHAPE.match(site):
        raise ValueError("Website is invalid.")
    return site


class CreateOrgRequest(BaseModel):
    """Create an org. Business kind requires tax plus legal representative."""

    name: Annotated[str, Field(min_length=2, max_length=100)]
    slug: str
    description: Annotated[str, Field(max_length=500)] = ""
    kind: OrgKind = "organization"
    join_policy: JoinPolicy = "invite"
    tax_code: str | None = None
    legal_rep_name: Annotated[str, Field(min_length=2, max_length=100)] | None = None
    legal_rep_id: str | None = None
    legal_rep_position: Annotated[str, Field(min_length=2, max_length=100)] | None = (
        None
    )
    email: str | None = None
    phone: Annotated[str, Field(max_length=20)] | None = None
    website: Annotated[str, Field(max_length=255)] | None = None
    address: Annotated[str, Field(max_length=255)] | None = None
    city: Annotated[str, Field(max_length=100)] | None = None
    country: Annotated[str, Field(max_length=100)] | None = None
    legal_name: Annotated[str, Field(max_length=255)] | None = None
    license_number: Annotated[str, Field(max_length=100)] | None = None
    is_personal: bool = False

    _slug = field_validator("slug", mode="before")(validate_slug)  # noqa: SLF001
    _tax = field_validator("tax_code", mode="before")(  # noqa: SLF001
        lambda v: validate_tax_code(v) if v not in (None, "") else v
    )
    _cccd = field_validator("legal_rep_id", mode="before")(  # noqa: SLF001
        lambda v: validate_cccd(v) if v not in (None, "") else v
    )
    _email = field_validator("email", mode="before")(  # noqa: SLF001
        lambda v: validate_contact_email(v) if v not in (None, "") else None
    )
    _phone = field_validator("phone", mode="before")(  # noqa: SLF001
        lambda v: validate_org_phone(v) if v not in (None, "") else None
    )
    _site = field_validator("website", mode="before")(  # noqa: SLF001
        lambda v: validate_website(v) if v not in (None, "") else None
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
    join_policy: JoinPolicy = "invite"
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    legal_name: str | None = None
    license_number: str | None = None
    is_personal: bool = False
    logo_media_id: UUID | None = None
    cover_media_id: UUID | None = None
    verified_at: datetime | None = None
    previous_slug: str | None = None
    deleted_at: datetime | None = None
    created_at: datetime


class BucketCount(BaseModel):
    """One status/kind facet for the mine/public filter chips."""

    bucket: str
    count: int


class OrgListPage(BaseModel):
    """One mine-listing page: items plus totals for chips and pager."""

    items: list[OrgResponse]
    total: int
    counts: list[BucketCount] = []


class PublicOrgResponse(BaseModel):
    """Guest-facing org card: no legal, contact or ownership fields."""

    id: UUID
    name: str
    slug: str
    description: str = ""
    kind: OrgKind
    member_count: int = 1
    join_policy: JoinPolicy = "invite"
    city: str | None = None
    country: str | None = None
    verified_at: datetime | None = None
    logo_url: str | None = None
    cover_url: str | None = None
    created_at: datetime


class PublicOrgPage(BaseModel):
    """One public-directory page: items plus kind chips and pager totals."""

    items: list[PublicOrgResponse]
    total: int
    counts: list[BucketCount] = []


class PublicOrgActivityItem(BaseModel):
    """One recent public activity teaser on the org profile."""

    id: UUID
    slug: str
    title: str
    status: str
    city: str | None = None
    start_at: datetime | None = None


class PublicOrgDetailResponse(BaseModel):
    """Guest-facing org profile; owner and legal-rep fields stay out."""

    id: UUID
    name: str
    slug: str
    description: str = ""
    kind: OrgKind
    member_count: int = 1
    join_policy: JoinPolicy = "invite"
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    legal_status: str = "none"
    legal_name: str | None = None
    license_number: str | None = None
    tax_code: str | None = None
    verified_at: datetime | None = None
    logo_url: str | None = None
    cover_url: str | None = None
    gallery: list[str] = []
    activity_count: int = 0
    activities: list[PublicOrgActivityItem] = []
    created_at: datetime


class UpdateOrgRequest(BaseModel):
    """Owner replaces details; slug/kind/tax stay frozen, null clears."""

    name: Annotated[str, Field(min_length=2, max_length=100)]
    description: Annotated[str, Field(max_length=500)] = ""
    join_policy: JoinPolicy | None = None
    email: str | None = None
    phone: Annotated[str, Field(max_length=20)] | None = None
    website: Annotated[str, Field(max_length=255)] | None = None
    address: Annotated[str, Field(max_length=255)] | None = None
    city: Annotated[str, Field(max_length=100)] | None = None
    country: Annotated[str, Field(max_length=100)] | None = None
    legal_name: Annotated[str, Field(max_length=255)] | None = None
    license_number: Annotated[str, Field(max_length=100)] | None = None
    is_personal: bool = False

    _email = field_validator("email", mode="before")(  # noqa: SLF001
        lambda v: validate_contact_email(v) if v not in (None, "") else None
    )
    _phone = field_validator("phone", mode="before")(  # noqa: SLF001
        lambda v: validate_org_phone(v) if v not in (None, "") else None
    )
    _site = field_validator("website", mode="before")(  # noqa: SLF001
        lambda v: validate_website(v) if v not in (None, "") else None
    )


class SetMediaRoleRequest(BaseModel):
    """Owner marks one image as the org cover/logo, or clears it."""

    role: MediaRole


class MediaResponse(BaseModel):
    """One gallery row: metadata plus the public file URL."""

    id: UUID
    org_id: UUID
    kind: str = "image"
    role: MediaRole = "gallery"
    mime: str
    size_bytes: int = 0
    file_url: str
    uploader_id: UUID | None = None
    original_name: str | None = None
    upload_status: str = "active"
    created_at: datetime
    updated_at: datetime | None = None
