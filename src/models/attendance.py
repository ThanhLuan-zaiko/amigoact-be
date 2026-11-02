"""Attendance and volunteer hour tables."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models import activities  # noqa: F401  registers the foreign key targets
from src.models.base import Base


class AttendanceSession(Base):
    __tablename__ = "attendance_sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("activity_schedules.id", ondelete="CASCADE")
    )
    title: Mapped[str | None]
    # The short code a volunteer types by hand. The long QR secret is in qr_codes.
    qr_code: Mapped[str | None]
    opens_at: Mapped[datetime | None]
    closes_at: Mapped[datetime | None]
    # Allowed values are enforced by a CHECK constraint in schema.sql.
    status: Mapped[str] = mapped_column(server_default="scheduled")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class QrCode(Base):
    __tablename__ = "qr_codes"

    code: Mapped[str] = mapped_column(primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("attendance_sessions.session_id", ondelete="CASCADE")
    )
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("activity_schedules.id", ondelete="CASCADE")
    )
    activity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE")
    )
    expires_at: Mapped[datetime | None]
    used_count: Mapped[int] = mapped_column(server_default="0")
    status: Mapped[str] = mapped_column(server_default="active")


class QrScanLog(Base):
    __tablename__ = "qr_scan_logs"

    log_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    # No foreign key: an invalid code is logged even though it does not exist.
    qr_code: Mapped[str]
    scanned_at: Mapped[datetime] = mapped_column(server_default=func.now())
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    result: Mapped[str]
    device_info: Mapped[str | None]


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"

    record_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("attendance_sessions.session_id", ondelete="CASCADE")
    )
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("activity_schedules.id", ondelete="CASCADE")
    )
    activity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE")
    )
    registration_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("registrations.registration_id", ondelete="CASCADE")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    # 'qr' counts at once. 'manual' counts only after a manager sets verified_by.
    method: Mapped[str]
    scanned_at: Mapped[datetime] = mapped_column(server_default=func.now())
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class AttendanceAppeal(Base):
    __tablename__ = "attendance_appeals"

    appeal_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    activity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    reason: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default="pending")
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class VolunteerHourLedger(Base):
    """Append-only: a correction is a new 'adjustment' row, never an edit."""

    __tablename__ = "volunteer_hour_ledger"

    entry_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    activity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("activities.id", ondelete="SET NULL")
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    source: Mapped[str]
    hours: Mapped[Decimal] = mapped_column(Numeric(7, 2))
    term: Mapped[str | None]
    registration_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("registrations.registration_id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(server_default="pending")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None]
    recorded_at: Mapped[datetime] = mapped_column(server_default=func.now())
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None]


class HourAdjustment(Base):
    __tablename__ = "hour_adjustments"

    adjustment_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid7
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    activity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("activities.id", ondelete="SET NULL")
    )
    delta_hours: Mapped[Decimal] = mapped_column(Numeric(7, 2))
    reason: Mapped[str | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class HourRule(Base):
    __tablename__ = "hour_rules"

    rule_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    category_id: Mapped[uuid.UUID | None]
    multiplier: Mapped[Decimal] = mapped_column(Numeric(6, 3), server_default="1")
    cap_hours: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    term: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(server_default="true")
