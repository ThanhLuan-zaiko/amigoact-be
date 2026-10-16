"""Request/response DTOs for the certificates API surface."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RevokeBody(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class CertificateResponse(BaseModel):
    certificate_id: UUID
    activity_id: UUID
    student_id: UUID
    serial_no: str
    status: str
    issued_at: datetime | None


class MyCertificateResponse(BaseModel):
    certificate_id: UUID
    activity_id: UUID
    activity_title: str
    serial_no: str
    status: str
    issued_at: datetime | None


class VerifyResponse(BaseModel):
    serial_no: str
    status: str
    activity_title: str
    student_name: str
    issued_at: datetime | None


class IssueBody(BaseModel):
    """Optional template picked for the issued certificate."""

    template_id: UUID | None = None


class TemplateBody(BaseModel):
    """Create a named background/layout template for the org."""

    name: str = Field(min_length=1, max_length=200)
    background_media_id: UUID | None = None
    layout_json: str | None = Field(default=None, max_length=20000)


class TemplatePatchBody(BaseModel):
    """Patch mutable template fields; omitted values stay untouched."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    background_media_id: UUID | None = None
    layout_json: str | None = Field(default=None, max_length=20000)
    is_active: bool | None = None


class TemplateResponse(BaseModel):
    """One template row as the library list shows it."""

    template_id: UUID
    org_id: UUID
    name: str | None
    background_media_id: UUID | None
    layout_json: str | None
    is_active: bool | None
    created_at: datetime | None
