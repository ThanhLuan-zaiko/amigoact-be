"""cqlengine models for the platform-admin bounded context."""

from __future__ import annotations

import core.database  # noqa: F401  (reactor compat shim must run first)
from cassandra.cqlengine import columns, models


class PlatformUserRole(models.Model):
    """Platform roles held by one user (the is-admin lookup)."""

    __table_name__ = "platform_user_roles"

    user_id = columns.UUID(primary_key=True, partition_key=True)
    role_id = columns.UUID(primary_key=True, clustering_order="ASC")
    granted_by = columns.UUID(required=True)
    granted_at = columns.DateTime(required=True)
    expires_at = columns.DateTime(required=False)


class PlatformRoleRoster(models.Model):
    """Reverse feed: every user holding one platform role."""

    __table_name__ = "platform_role_roster"

    role_id = columns.UUID(primary_key=True, partition_key=True)
    user_id = columns.UUID(primary_key=True, clustering_order="ASC")
    granted_by = columns.UUID(required=True)
    granted_at = columns.DateTime(required=True)
    expires_at = columns.DateTime(required=False)


class MediaModeration(models.Model):
    """Moderation queue bucketed by status (pending/approved/rejected)."""

    __table_name__ = "media_moderation"

    status = columns.Text(primary_key=True, partition_key=True)
    created_at = columns.DateTime(primary_key=True, clustering_order="DESC")
    moderation_id = columns.UUID(primary_key=True)
    asset_id = columns.UUID(required=True)
    reviewed_by = columns.UUID(required=False)
    note = columns.Text(required=False)
