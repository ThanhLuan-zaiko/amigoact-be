"""Pydantic DTOs for the profiles HTTP contract."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

_PROFILE_STATUSES = {"studying", "graduated", "suspended"}


class SkillItem(BaseModel):
    """One catalog row as pickers render it."""

    id: UUID
    name: str
    slug: str


class SkillEdgeItem(SkillItem):
    """A catalog row plus the user's self-declared level."""

    level: int = Field(ge=1, le=5)


class SkillEdgeIn(BaseModel):
    """One edge inside the set-skills payload."""

    skill_id: UUID
    level: int = Field(ge=1, le=5)


class ContactItem(BaseModel):
    """One emergency contact row."""

    contact_id: UUID
    name: str
    relation: str | None
    phone: str
    is_primary: bool


class ContactCreate(BaseModel):
    """Payload for POST /profiles/me/contacts."""

    name: str = Field(min_length=1, max_length=120)
    relation: str | None = Field(default=None, max_length=60)
    phone: str = Field(min_length=8, max_length=20)
    is_primary: bool = False


class ProfileBody(BaseModel):
    """Editable profile fields in PUT /profiles/me (full replace)."""

    student_code: str | None = Field(default=None, max_length=40)
    class_name: str | None = Field(default=None, max_length=60)
    enrollment_year: int | None = Field(default=None, ge=1950, le=2100)
    school_name: str | None = Field(default=None, max_length=160)
    bio: str | None = Field(default=None, max_length=2000)
    interests: list[str] = Field(default_factory=list, max_length=20)
    status: str | None = None

    @field_validator("status")
    @classmethod
    def _status_ok(cls, value: str | None) -> str | None:
        if value is not None and value not in _PROFILE_STATUSES:
            raise ValueError("status must be studying|graduated|suspended")
        return value


class SetSkillsBody(BaseModel):
    """Whole-set replace payload for PUT /profiles/me/skills."""

    skills: list[SkillEdgeIn] = Field(default_factory=list, max_length=20)


class ProfileResponse(BaseModel):
    """Everything /profiles/me renders: profile, skills, contacts, avatar."""

    student_code: str | None
    class_name: str | None
    enrollment_year: int | None
    school_name: str | None
    bio: str | None
    interests: list[str]
    status: str | None
    total_hours: float
    updated_at: datetime | None
    skills: list[SkillEdgeItem]
    contacts: list[ContactItem]
    avatar_url: str | None


class PublicProfileResponse(BaseModel):
    """Volunteer card for public pages; no contact/PII leakage."""

    full_name: str
    school_name: str | None
    class_name: str | None
    bio: str | None
    interests: list[str]
    total_hours: float
    skills: list[SkillEdgeItem]
    avatar_url: str | None
    member_since: datetime | None


class AvatarResponse(BaseModel):
    """Fresh avatar URL after a successful upload."""

    avatar_url: str
