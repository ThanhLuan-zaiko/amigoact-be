"""Authentication tables: users, tokens, sessions, and rate limits."""

import uuid
from datetime import date, datetime

from sqlalchemy import ForeignKey, func
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    email: Mapped[str] = mapped_column(CITEXT)
    phone: Mapped[str | None]
    password_hash: Mapped[str | None]
    full_name: Mapped[str]
    # Allowed values are enforced by a CHECK constraint in schema.sql.
    account_type: Mapped[str] = mapped_column(server_default="individual")
    tax_code: Mapped[str | None]
    company_name: Mapped[str | None]
    legal_rep_name: Mapped[str | None]
    legal_rep_id: Mapped[str | None]
    legal_rep_position: Mapped[str | None]
    date_of_birth: Mapped[date | None]
    # Allowed values are enforced by a CHECK constraint in schema.sql.
    gender: Mapped[str | None]
    address: Mapped[str | None]
    # The foreign key to media_assets is added by schema.sql after that table exists.
    avatar_media_id: Mapped[uuid.UUID | None]
    last_login_at: Mapped[datetime | None]
    last_seen_at: Mapped[datetime | None]
    email_verified_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(server_default="active")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Kept current by the set_updated_at trigger, not by the ORM.
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AuthRefreshToken(Base):
    __tablename__ = "auth_refresh_tokens"

    # Only the SHA-256 hash of the opaque token is stored.
    token_hash: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    family_id: Mapped[uuid.UUID]
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    rotated_from: Mapped[str | None] = mapped_column(
        ForeignKey("auth_refresh_tokens.token_hash", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    device_label: Mapped[str | None]
    user_agent: Mapped[str | None]
    ip: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_seen_at: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]
    # A revoked session stays revoked even if it has not expired yet.
    revoked_at: Mapped[datetime | None]


class PasswordReset(Base):
    __tablename__ = "password_resets"

    token_hash: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]


class EmailVerification(Base):
    __tablename__ = "email_verifications"

    token_hash: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    email: Mapped[str] = mapped_column(CITEXT)
    expires_at: Mapped[datetime]
    verified_at: Mapped[datetime | None]


class AuthRateLimit(Base):
    __tablename__ = "auth_rate_limits"

    # Examples: 'login:<ip>', 'refresh:<user_id>', 'edge:<ip>'.
    bucket: Mapped[str] = mapped_column(primary_key=True)
    window_start: Mapped[datetime] = mapped_column(primary_key=True)
    hits: Mapped[int] = mapped_column(server_default="0")
