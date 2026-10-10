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
