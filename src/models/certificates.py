"""Certificate tables: templates, issued certificates, and their revocations."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models import activities, auth, media, organizations  # noqa: F401  registers the foreign key targets
from src.models.base import Base


class CertificateTemplate(Base):
    __tablename__ = "certificate_templates"

    template_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str]
    background_media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_assets.asset_id", ondelete="SET NULL")
    )
    # Where each text goes on the page. Checked by the schemas before it is stored.
    layout_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    is_active: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Certificate(Base):
    __tablename__ = "certificates"

    certificate_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid7
    )
    activity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    registration_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("registrations.registration_id", ondelete="SET NULL")
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("certificate_templates.template_id", ondelete="SET NULL")
    )
    serial_no: Mapped[str]
    issued_at: Mapped[datetime] = mapped_column(server_default=func.now())
    issued_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(server_default="issued")


class CertificateRevocation(Base):
    __tablename__ = "certificate_revocations"

    revocation_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid7
    )
    certificate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("certificates.certificate_id", ondelete="CASCADE")
    )
    reason: Mapped[str | None]
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime] = mapped_column(server_default=func.now())
