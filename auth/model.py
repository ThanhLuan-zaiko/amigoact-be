"""cqlengine models for the auth bounded context (persistence only)."""

from __future__ import annotations

import core.database  # noqa: F401  (reactor compat shim must run first)
from core.ids import uuid7
from cassandra.cqlengine import columns, models


class User(models.Model):
    """Primary user row. Email/phone uniqueness lives in index tables."""

    __table_name__ = "users"

    id = columns.UUID(primary_key=True, default=uuid7)
    email = columns.Text(required=True)
    phone = columns.Text(required=True)
    password_hash = columns.Text(required=True)
    full_name = columns.Text(required=True)
    account_type = columns.Text(required=True, default="individual")
    tax_code = columns.Text(required=False)
    company_name = columns.Text(required=False)
    legal_rep_name = columns.Text(required=False)
    legal_rep_id = columns.Text(required=False)
    legal_rep_position = columns.Text(required=False)
    date_of_birth = columns.Date(required=False)
    gender = columns.Text(required=False)
    address = columns.Text(required=False)
    avatar_media_id = columns.UUID(required=False)
    last_login_at = columns.DateTime(required=False)
    # User-level presence stamp written on socket connect/disconnect.
    last_seen_at = columns.DateTime(required=False)
    email_verified_at = columns.DateTime(required=False)
    status = columns.Text(required=True, default="active")
    created_at = columns.DateTime(required=True)
    updated_at = columns.DateTime(required=True)


class UsersByEmail(models.Model):
    """Unique email index. Claimed with LWT (IF NOT EXISTS) on register."""

    __table_name__ = "users_by_email"

    email = columns.Text(primary_key=True)
    user_id = columns.UUID(required=True)


class UsersByPhone(models.Model):
    """Unique phone index. Claimed with LWT (IF NOT EXISTS) on register."""

    __table_name__ = "users_by_phone"

    phone = columns.Text(primary_key=True)
    user_id = columns.UUID(required=True)


class AuthRefreshToken(models.Model):
    """Stored SHA-256 digests of opaque refresh tokens (never plaintext)."""

    __table_name__ = "auth_refresh_tokens"

    token_hash = columns.Text(primary_key=True)
    user_id = columns.UUID(required=True)
    family_id = columns.UUID(required=True, default=uuid7)
    expires_at = columns.DateTime(required=True)
    revoked_at = columns.DateTime(required=False)
    rotated_from = columns.Text(required=False)
    created_at = columns.DateTime(required=True)


class EmailVerification(models.Model):
    """Single-use numeric verification codes, stored as digests."""

    __table_name__ = "email_verifications"

    token_hash = columns.Text(primary_key=True)
    user_id = columns.UUID(required=True)
    email = columns.Text(required=True)
    expires_at = columns.DateTime(required=True)
    verified_at = columns.DateTime(required=False)


class PasswordReset(models.Model):
    """Single-use numeric password reset codes, stored as digests."""

    __table_name__ = "password_resets"

    token_hash = columns.Text(primary_key=True)
    user_id = columns.UUID(required=True)
    expires_at = columns.DateTime(required=True)
    used_at = columns.DateTime(required=False)


class RefreshTokenByUser(models.Model):
    """Query table: list every refresh digest owned by one user."""

    __table_name__ = "refresh_tokens_by_user"

    user_id = columns.UUID(primary_key=True, partition_key=True)
    token_hash = columns.Text(primary_key=True, clustering_order="ASC")
    family_id = columns.UUID(required=True)
    expires_at = columns.DateTime(required=True)
    revoked_at = columns.DateTime(required=False)


class RefreshTokenByFamily(models.Model):
    """Query table: list every refresh digest of one token family."""

    __table_name__ = "refresh_tokens_by_family"

    family_id = columns.UUID(primary_key=True, partition_key=True)
    token_hash = columns.Text(primary_key=True, clustering_order="ASC")
    user_id = columns.UUID(required=True)
    expires_at = columns.DateTime(required=True)
    revoked_at = columns.DateTime(required=False)


class AuthSession(models.Model):
    """Per-device login session; session_id mirrors the token family."""

    __table_name__ = "auth_sessions"

    user_id = columns.UUID(primary_key=True, partition_key=True)
    session_id = columns.UUID(primary_key=True)
    device_label = columns.Text(required=False)
    user_agent = columns.Text(required=False)
    ip = columns.Text(required=False)
    created_at = columns.DateTime(required=True)
    last_seen_at = columns.DateTime(required=False)
    expires_at = columns.DateTime(required=False)
    revoked_at = columns.DateTime(required=False)
