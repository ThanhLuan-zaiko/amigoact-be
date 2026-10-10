"""Pydantic DTOs for the registrations HTTP contract."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ApplyBody(BaseModel):
    """Optional motivation note attached to an application."""

    note: str | None = Field(default=None, max_length=1000)


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
