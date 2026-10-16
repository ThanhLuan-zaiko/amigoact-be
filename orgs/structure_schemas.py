"""Pydantic DTOs for the org campus/department structure."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field




class CampusBody(BaseModel):
    """Create payload for one campus."""

    name: str = Field(min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=500)


class CampusPatchBody(BaseModel):
    """Patch payload for one campus."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    status: str | None = Field(default=None, pattern="^(active|archived)$")


class CampusResponse(BaseModel):
    """Campus row as returned to managers and members."""

    id: UUID
    org_id: UUID
    name: str
    address: str | None
    status: str


class DepartmentBody(BaseModel):
    """Create payload for one department."""

    name: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=50)
    campus_id: UUID | None = None


class DepartmentPatchBody(BaseModel):
    """Patch payload for one department."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=50)
    campus_id: UUID | None = None
    status: str | None = Field(default=None, pattern="^(active|archived)$")


class DepartmentResponse(BaseModel):
    """Department row as returned to managers and members."""

    id: UUID
    org_id: UUID
    campus_id: UUID | None
    name: str
    code: str | None
    status: str


class StudentLookupResponse(BaseModel):
    """Resolved student code; user_id null when not found."""

    user_id: UUID | None
    student_code: str


class OrgTypeResponse(BaseModel):
    """One org-kind lookup row."""

    code: str
    name: str
    sort_order: int
