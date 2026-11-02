"""Request and response bodies of the certificate API."""

import uuid
from datetime import datetime

from pydantic import BaseModel

from src.attendance.schemas import Reason
from src.organizations.schemas import StrictRequest
from src.validation import Uuid7


class RevokeRequest(StrictRequest):
    reason: Reason


class IssueRequest(StrictRequest):
    # Optional. Without it, certificates are issued with no template.
    template_id: Uuid7 | None = None


class IssueResult(BaseModel):
    issued: int


class CertificateEntry(BaseModel):
    """One row for a manager. Contact details stay out, as in the other lists."""

    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    serial_no: str
    status: str
    hours: float
    issued_at: datetime


class ActivityCertificates(BaseModel):
    items: list[CertificateEntry]
    # People who attended and have no certificate yet.
    missing_count: int


class MyCertificate(BaseModel):
    id: uuid.UUID
    serial_no: str
    status: str
    hours: float
    issued_at: datetime
    activity_id: uuid.UUID
    activity_title: str
    organization_name: str


class VerifiedCertificate(BaseModel):
    """Public, so it holds only what proves the certificate and nothing to contact."""

    serial_no: str
    status: str
    full_name: str
    hours: float
    issued_at: datetime
    revoked_at: datetime | None
    activity_title: str
    activity_start_at: datetime | None
    organization_name: str
