"""Pydantic DTOs for the activities HTTP contract."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

_SLUG = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
_PARTNER_ROLES = {"co_organizer", "sponsor"}
_STAFF_ROLES = {"organizer", "supervisor", "supporter"}


def slugify(value: str) -> str:
    """ASCII slug from a title; strips Vietnamese diacritics."""
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", value)
    text = text.replace("\u0111", "d").replace("\u0110", "D")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return re.sub(r"-{2,}", "-", text) or "hoat-dong"


class ActivityBody(BaseModel):
    """Editable activity fields in create/update (full replace)."""

    title: str = Field(min_length=3, max_length=160)
    slug: str | None = Field(default=None, pattern=_SLUG, max_length=80)
    description: str | None = Field(default=None, max_length=5000)
    category_id: UUID | None = None
    location: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=80)
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    is_remote: bool = False
    max_participants: int | None = Field(default=None, ge=1)
    start_at: datetime
    end_at: datetime | None = None
    hours_awarded: float = Field(default=0.0, ge=0.0)
    registration_deadline: datetime | None = None
    person_in_charge_id: UUID | None = None

    @field_validator("end_at")
    @classmethod
    def _end_after_start(cls, value: datetime | None, info) -> datetime | None:  # noqa: ANN001
        start = info.data.get("start_at")
        if value is not None and start is not None and value <= start:
            raise ValueError("end_at must be after start_at")
        return value


class ActivityResponse(BaseModel):
    """Full activity row as detail and manage screens render it."""

    id: UUID
    org_id: UUID
    title: str
    slug: str
    description: str
    category_id: UUID | None
    status: str
    location: str | None
    address: str | None
    city: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    is_remote: bool
    max_participants: int | None
    start_at: datetime | None
    end_at: datetime | None
    hours_awarded: float
    registration_deadline: datetime | None
    person_in_charge_id: UUID | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ActivitySummary(BaseModel):
    """Feed item for discovery and org lists."""

    id: UUID
    org_id: UUID
    title: str
    slug: str
    status: str
    start_at: datetime | None
    category_id: UUID | None


class DiscoveryBucket(BaseModel):
    """One discovery shelf: category plus a few public items."""

    category_id: UUID
    name: str
    items: list[ActivitySummary]


class DiscoveryResponse(BaseModel):
    """Curated sections for the public discovery page."""

    featured: list[ActivitySummary]
    upcoming: list[ActivitySummary]
    categories: list[DiscoveryBucket]


class CategoryCreate(BaseModel):
    """Payload for org-scoped categories."""

    name: str = Field(min_length=2, max_length=80)
    slug: str = Field(pattern=_SLUG, max_length=60)
    description: str | None = Field(default=None, max_length=300)
    icon: str | None = Field(default=None, max_length=40)
    default_hours: float | None = Field(default=None, ge=0.0)
    color: str | None = Field(default=None, max_length=20)


class CategoryItem(BaseModel):
    """One catalog row for pickers."""

    id: UUID
    name: str
    slug: str
    org_scoped: bool
    default_hours: float | None


class SkillEdgeBody(BaseModel):
    """One skill edge inside the replace payload."""

    skill_id: UUID
    is_required: bool = False


class SetSkillsBody(BaseModel):
    skills: list[SkillEdgeBody] = Field(default_factory=list, max_length=15)


class PartnerBody(BaseModel):
    """One partner edge inside the replace payload."""

    org_id: UUID
    role: str
    note: str | None = Field(default=None, max_length=200)

    @field_validator("role")
    @classmethod
    def _role_ok(cls, value: str) -> str:
        if value not in _PARTNER_ROLES:
            raise ValueError("role must be co_organizer|sponsor")
        return value


class SetPartnersBody(BaseModel):
    partners: list[PartnerBody] = Field(default_factory=list, max_length=10)


class StaffBody(BaseModel):
    """One staff assignment inside the replace payload."""

    user_id: UUID
    staff_role: str

    @field_validator("staff_role")
    @classmethod
    def _role_ok(cls, value: str) -> str:
        if value not in _STAFF_ROLES:
            raise ValueError("staff_role must be organizer|supervisor|supporter")
        return value


class SetStaffBody(BaseModel):
    staff: list[StaffBody] = Field(default_factory=list, max_length=30)


class ScheduleBody(BaseModel):
    """Payload for one activity session."""

    title: str = Field(min_length=2, max_length=120)
    location: str | None = Field(default=None, max_length=200)
    start_at: datetime | None = None
    end_at: datetime | None = None


class AnnouncementBody(BaseModel):
    """Payload for one news-board post."""

    title: str = Field(min_length=2, max_length=160)
    body: str = Field(default="", max_length=3000)


class SkillEdgeDetail(BaseModel):
    skill_id: UUID
    name: str
    slug: str
    is_required: bool


class PartnerDetail(BaseModel):
    org_id: UUID
    name: str
    role: str
    note: str | None


class StaffDetail(BaseModel):
    user_id: UUID
    full_name: str
    staff_role: str
    assigned_at: datetime | None


class ScheduleItem(BaseModel):
    id: UUID
    title: str
    location: str | None
    start_at: datetime | None
    end_at: datetime | None
    status: str


class AnnouncementItem(BaseModel):
    announcement_id: UUID
    title: str
    body: str
    published_at: datetime


class ActivityDetailResponse(BaseModel):
    """Composed detail payload for the event page."""

    activity: ActivityResponse
    skills: list[SkillEdgeDetail]
    partners: list[PartnerDetail]
    staff: list[StaffDetail]
    schedules: list[ScheduleItem]
    announcements: list[AnnouncementItem]
