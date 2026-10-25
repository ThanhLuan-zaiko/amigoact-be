"""Pydantic DTOs for the registrations HTTP contract."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field
from typing import Literal


class ApplyBody(BaseModel):
    """Optional motivation note plus custom-form answers (question_id -> text)."""

    note: str | None = Field(default=None, max_length=1000)
    form_data: dict[str, str] | None = Field(default=None, max_length=64)
    slot_id: UUID | None = None


class ReviewBody(BaseModel):
    """Manager decision on a pending application."""

    status: str
    review_note: str | None = Field(default=None, max_length=500)


class CheckinBody(BaseModel):
    """Staff-side personal-QR payload."""

    checkin_token: UUID


class CheckoutBody(BaseModel):
    """Optional staff override of computed attendance hours."""

    actual_hours: float | None = Field(default=None, ge=0.0, le=100.0)


class RegistrationResponse(BaseModel):
    """One application row as both sides see it."""

    registration_id: UUID
    activity_id: UUID
    student_id: UUID
    status: str
    note: str | None
    review_note: str | None
    registered_at: datetime | None
    reviewed_at: datetime | None
    cancelled_at: datetime | None
    slot_id: UUID | None = None


class RosterResponse(BaseModel):
    """Manager roster row with applicant contact."""

    registration_id: UUID
    student_id: UUID
    student_name: str
    student_email: str | None
    status: str
    note: str | None
    review_note: str | None
    registered_at: datetime | None
    form_data: dict[str, str] | None = None
    slot_id: UUID | None = None


class SessionBody(BaseModel):
    """Manager payload to mint a check-in session."""

    title: str = Field(min_length=1, max_length=120)
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    max_uses: int | None = Field(default=None, ge=1)


class SessionResponse(BaseModel):
    """One session plus its public QR code string."""

    session_id: UUID
    schedule_id: UUID
    title: str
    qr_code: str
    opens_at: datetime | None
    closes_at: datetime | None
    status: str


class ScanBody(BaseModel):
    """Student scan payload: the code string plus optional device tag."""

    code: str = Field(min_length=1, max_length=64)
    device_info: str | None = Field(default=None, max_length=255)


class ScanLogResponse(BaseModel):
    """One audit row of a scan attempt on a code."""

    scanned_at: datetime | None
    student_id: UUID
    result: str
    device_info: str | None


class HistoryEntryResponse(BaseModel):
    """One audit row: status transition with actor and note."""

    from_status: str | None
    to_status: str
    changed_at: datetime | None
    changed_by: UUID | None
    note: str | None


class TicketResponse(BaseModel):
    """Personal QR payload rendered by the applicant's device."""

    registration_id: UUID
    checkin_token: UUID
    activity_id: UUID
    status: str


class AttendanceResponse(BaseModel):
    """One check-in/out row as rosters and history show it."""

    record_id: UUID
    activity_id: UUID
    student_id: UUID
    session_id: UUID | None
    method: str
    scanned_at: datetime | None
    checked_out_at: datetime | None
    check_out_method: str | None
    actual_hours: float | None


class AppealBody(BaseModel):
    """Student filing an attendance appeal."""

    reason: str = Field(min_length=3, max_length=2000)
    record_id: UUID | None = None


class AppealResolveBody(BaseModel):
    """Manager verdict on a pending appeal."""

    status: Literal["approved", "rejected"]


class AppealResponse(BaseModel):
    """One appeal row as queues and students see it."""

    activity_id: UUID
    student_id: UUID
    appeal_id: UUID
    record_id: UUID | None
    reason: str
    status: str
    resolved_by: UUID | None
    resolved_at: datetime | None
    created_at: datetime | None


class SummaryResponse(BaseModel):
    """Attendance rollup for one registration."""

    registration_id: UUID
    activity_id: UUID
    student_id: UUID
    sessions_total: int
    sessions_attended: int
    minutes_attended: int
    status: str
    updated_at: datetime | None


class RegistrationBriefResponse(BaseModel):
    """The caller's best registration status for one activity."""

    activity_id: UUID
    registration_id: UUID
    status: str
    registered_at: datetime | None
