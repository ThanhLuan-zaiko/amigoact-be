"""Media registry: one row per uploaded file. The bytes live on the local disk."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models import auth  # noqa: F401  registers users for the foreign keys
from src.models.base import Base


class MediaAsset(Base):
    __tablename__ = "media_assets"

    asset_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    # Owner types and roles are enforced by CHECK constraints in schema.sql.
    owner_id: Mapped[uuid.UUID | None]
    owner_type: Mapped[str]
    file_hash: Mapped[str | None]
    mime: Mapped[str | None]
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    role: Mapped[str | None]
    uploader_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    storage_key: Mapped[str | None]
    backend: Mapped[str | None] = mapped_column(server_default="local")
    original_name: Mapped[str | None]
    visibility: Mapped[str] = mapped_column(server_default="private")
    upload_status: Mapped[str] = mapped_column(server_default="pending")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Kept current by the set_updated_at trigger, not by the ORM.
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    deleted_at: Mapped[datetime | None]
