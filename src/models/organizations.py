"""Organization tables: organizations, members, applications, and org roles."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, func
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models import auth, media  # noqa: F401  registers the foreign key targets
from src.models.base import Base


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    name: Mapped[str]
    slug: Mapped[str] = mapped_column(CITEXT)
    description: Mapped[str | None]
    # Allowed values are enforced by CHECK constraints in schema.sql.
    org_type: Mapped[str] = mapped_column(server_default="organization")
    status: Mapped[str] = mapped_column(server_default="active")
    join_policy: Mapped[str] = mapped_column(server_default="invite")
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    email: Mapped[str | None]
    phone: Mapped[str | None]
    website: Mapped[str | None]
    address: Mapped[str | None]
    city: Mapped[str | None]
    # Legal details. Only a platform admin moves legal_status away from 'none'.
    legal_name: Mapped[str | None]
    tax_code: Mapped[str | None]
    license_number: Mapped[str | None]
    legal_rep_name: Mapped[str | None]
    legal_rep_position: Mapped[str | None]
    legal_status: Mapped[str] = mapped_column(server_default="none")
    logo_media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_assets.asset_id", ondelete="SET NULL")
    )
    cover_media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_assets.asset_id", ondelete="SET NULL")
    )
    # Set by a soft delete. NULL means the organization is alive.
    deleted_at: Mapped[datetime | None]
    # The slug the organization had before a soft delete released it.
    previous_slug: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Kept current by the set_updated_at trigger, not by the ORM.
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class OrganizationMedia(Base):
    __tablename__ = "organization_media"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("media_assets.asset_id", ondelete="CASCADE"), primary_key=True
    )
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class OrganizationMember(Base):
    __tablename__ = "organization_members"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Allowed values are enforced by a CHECK constraint in schema.sql.
    status: Mapped[str]
    joined_at: Mapped[datetime | None]


class MembershipApplication(Base):
    __tablename__ = "membership_applications"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    answers: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    submitted_at: Mapped[datetime | None]
    # Stays after a rejection, so it controls when the user may apply again.
    rejected_at: Mapped[datetime | None]


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    code: Mapped[str]
    name: Mapped[str]
    is_system: Mapped[bool] = mapped_column(server_default="false")
    position: Mapped[int] = mapped_column(server_default="0")


class UserRole(Base):
    __tablename__ = "user_roles"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime | None]
