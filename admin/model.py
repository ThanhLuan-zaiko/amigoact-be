"""cqlengine models for the platform-admin bounded context."""

from __future__ import annotations

import core.database  # noqa: F401  (reactor compat shim must run first)
from cassandra.cqlengine import columns, models


class PlatformUserRole(models.Model):
    """Platform roles held by one user (the is-admin lookup)."""

    __table_name__ = "platform_user_roles"
    __keyspace__ = "amigoact"

    user_id = columns.UUID(primary_key=True, partition_key=True)
    role_id = columns.UUID(primary_key=True, clustering_order="ASC")
    granted_by = columns.UUID(required=True)
    granted_at = columns.DateTime(required=True)
    expires_at = columns.DateTime(required=False)


class PlatformRoleRoster(models.Model):
    """Reverse feed: every user holding one platform role."""

    __table_name__ = "platform_role_roster"
    __keyspace__ = "amigoact"

    role_id = columns.UUID(primary_key=True, partition_key=True)
    user_id = columns.UUID(primary_key=True, clustering_order="ASC")
    granted_by = columns.UUID(required=True)
    granted_at = columns.DateTime(required=True)
    expires_at = columns.DateTime(required=False)
