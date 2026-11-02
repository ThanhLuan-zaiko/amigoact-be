"""Activity tables: activities, their shifts, and registrations."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models import organizations  # noqa: F401  registers the foreign key targets
from src.models.base import Base


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    title: Mapped[str]
    description: Mapped[str | None]
    # Allowed values are enforced by a CHECK constraint in schema.sql.
    status: Mapped[str] = mapped_column(server_default="draft")
    location: Mapped[str | None]
    address: Mapped[str | None]
    city: Mapped[str | None]
    is_remote: Mapped[bool] = mapped_column(server_default="false")
    max_participants: Mapped[int | None]
    start_at: Mapped[datetime | None]
    end_at: Mapped[datetime | None]
    registration_deadline: Mapped[datetime | None]
    hours_awarded: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    requirements_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    published_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Kept current by the set_updated_at trigger, not by the ORM.
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ActivitySchedule(Base):
    __tablename__ = "activity_schedules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    activity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE")
    )
    title: Mapped[str | None]
    location: Mapped[str | None]
    start_at: Mapped[datetime | None]
    end_at: Mapped[datetime | None]


class ActivitySlot(Base):
    __tablename__ = "activity_slots"

    slot_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("activity_schedules.id", ondelete="CASCADE")
    )
    title: Mapped[str | None]
    capacity: Mapped[int | None]
    registered: Mapped[int] = mapped_column(server_default="0")
    start_at: Mapped[datetime | None]
    end_at: Mapped[datetime | None]


class Registration(Base):
    __tablename__ = "registrations"

    registration_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid7
    )
    activity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    slot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("activity_slots.slot_id", ondelete="RESTRICT")
    )
    # Allowed values are enforced by a CHECK constraint in schema.sql.
    status: Mapped[str] = mapped_column(server_default="pending")
    note: Mapped[str | None]
    review_note: Mapped[str | None]
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None]
    checkin_token: Mapped[uuid.UUID]
    registered_at: Mapped[datetime] = mapped_column(server_default=func.now())
    cancelled_at: Mapped[datetime | None]


class RegistrationStatusHistory(Base):
    __tablename__ = "registration_status_history"

    history_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    registration_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("registrations.registration_id", ondelete="CASCADE")
    )
    changed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    from_status: Mapped[str | None]
    to_status: Mapped[str]
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None]
