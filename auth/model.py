"""cqlengine models for the auth bounded context (persistence only)."""

from __future__ import annotations

import core.database  # noqa: F401  (reactor compat shim must run first)
from core.ids import uuid7
from cassandra.cqlengine import columns, models


class User(models.Model):
    """Primary user row. Email/phone uniqueness lives in index tables."""

    __table_name__ = "users"
    __keyspace__ = "amigoact"

    id = columns.UUID(primary_key=True, default=uuid7)
    email = columns.Text(required=True)
    phone = columns.Text(required=True)
    password_hash = columns.Text(required=True)
    full_name = columns.Text(required=True)
    email_verified_at = columns.DateTime(required=False)
    status = columns.Text(required=True, default="active")
    created_at = columns.DateTime(required=True)
    updated_at = columns.DateTime(required=True)


class UsersByEmail(models.Model):
    """Unique email index. Claimed with LWT (IF NOT EXISTS) on register."""

    __table_name__ = "users_by_email"
    __keyspace__ = "amigoact"

    email = columns.Text(primary_key=True)
    user_id = columns.UUID(required=True)


class UsersByPhone(models.Model):
    """Unique phone index. Claimed with LWT (IF NOT EXISTS) on register."""

    __table_name__ = "users_by_phone"
    __keyspace__ = "amigoact"

    phone = columns.Text(primary_key=True)
    user_id = columns.UUID(required=True)


class AuthRefreshToken(models.Model):
    """Stored SHA-256 digests of opaque refresh tokens (never plaintext)."""

    __table_name__ = "auth_refresh_tokens"
    __keyspace__ = "amigoact"

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
    __keyspace__ = "amigoact"

    token_hash = columns.Text(primary_key=True)
    user_id = columns.UUID(required=True)
    email = columns.Text(required=True)
    expires_at = columns.DateTime(required=True)
    verified_at = columns.DateTime(required=False)


class PasswordReset(models.Model):
    """Single-use numeric password reset codes, stored as digests."""

    __table_name__ = "password_resets"
    __keyspace__ = "amigoact"

    token_hash = columns.Text(primary_key=True)
    user_id = columns.UUID(required=True)
    expires_at = columns.DateTime(required=True)
    used_at = columns.DateTime(required=False)


class RefreshTokenByUser(models.Model):
    """Query table: list every refresh digest owned by one user."""

    __table_name__ = "refresh_tokens_by_user"
    __keyspace__ = "amigoact"

    user_id = columns.UUID(primary_key=True, partition_key=True)
    token_hash = columns.Text(primary_key=True, clustering_order="ASC")
    family_id = columns.UUID(required=True)
    expires_at = columns.DateTime(required=True)
    revoked_at = columns.DateTime(required=False)


class RefreshTokenByFamily(models.Model):
    """Query table: list every refresh digest of one token family."""

    __table_name__ = "refresh_tokens_by_family"
    __keyspace__ = "amigoact"

    family_id = columns.UUID(primary_key=True, partition_key=True)
    token_hash = columns.Text(primary_key=True, clustering_order="ASC")
    user_id = columns.UUID(required=True)
    expires_at = columns.DateTime(required=True)
    revoked_at = columns.DateTime(required=False)
