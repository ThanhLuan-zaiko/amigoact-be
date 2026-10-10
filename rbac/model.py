"""cqlengine models for the rbac bounded context (persistence only)."""

from __future__ import annotations

import core.database  # noqa: F401  (reactor compat shim must run first)
from core.ids import uuid7
from cassandra.cqlengine import columns, models


class Role(models.Model):
    """Role row; org_id null marks a platform system role."""

    __table_name__ = "roles"
    __keyspace__ = "amigoact"

    id = columns.UUID(primary_key=True, default=uuid7)
    org_id = columns.UUID(required=False)
    code = columns.Text(required=False)
    name = columns.Text(required=True)
    description = columns.Text(required=False, default="")
    is_system = columns.Boolean(required=True, default=False)
    created_at = columns.DateTime(required=True)


class RolesByOrg(models.Model):
    """Custom roles owned by one org (org-defined roles land later)."""

    __table_name__ = "roles_by_org"
    __keyspace__ = "amigoact"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    role_id = columns.UUID(primary_key=True, clustering_order="ASC")
    name = columns.Text(required=True)


class Permission(models.Model):
    """Stable permission code catalog (seeded, read-heavy)."""

    __table_name__ = "permissions"
    __keyspace__ = "amigoact"

    code = columns.Text(primary_key=True)
    module = columns.Text(required=True)
    description = columns.Text(required=False, default="")


class RolePermission(models.Model):
    """Permission codes attached to one role."""

    __table_name__ = "role_permissions"
    __keyspace__ = "amigoact"

    role_id = columns.UUID(primary_key=True, partition_key=True)
    permission_code = columns.Text(primary_key=True, clustering_order="ASC")


class UserRole(models.Model):
    """Role assignments partitioned by org for roster rendering."""

    __table_name__ = "user_roles"
    __keyspace__ = "amigoact"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    user_id = columns.UUID(primary_key=True, clustering_order="ASC")
    role_id = columns.UUID(primary_key=True, clustering_order="ASC")
    granted_by = columns.UUID(required=True)
    granted_at = columns.DateTime(required=True)
    expires_at = columns.DateTime(required=False)


class RolesByUser(models.Model):
    """Reverse view: every role one user holds, partitioned by user."""

    __table_name__ = "roles_by_user"
    __keyspace__ = "amigoact"

    user_id = columns.UUID(primary_key=True, partition_key=True)
    org_id = columns.UUID(primary_key=True, clustering_order="ASC")
    role_id = columns.UUID(primary_key=True, clustering_order="ASC")
    granted_at = columns.DateTime(required=True)
    expires_at = columns.DateTime(required=False)


class UserPermissionGrant(models.Model):
    """Direct per-user permission grant inside one org."""

    __table_name__ = "user_permission_grants"
    __keyspace__ = "amigoact"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    user_id = columns.UUID(primary_key=True, clustering_order="ASC")
    permission_code = columns.Text(primary_key=True, clustering_order="ASC")
    reason = columns.Text(required=False, default="")
    granted_by = columns.UUID(required=True)
    granted_at = columns.DateTime(required=True)
    expires_at = columns.DateTime(required=False)


class AccessAuditLog(models.Model):
    """Append-only authorization trail per org; newest first."""

    __table_name__ = "access_audit_logs"
    __keyspace__ = "amigoact"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    occurred_at = columns.DateTime(primary_key=True, clustering_order="DESC")
    log_id = columns.UUID(
        primary_key=True, clustering_order="ASC", default=uuid7
    )
    actor_id = columns.UUID(required=True)
    action = columns.Text(required=True)
    resource_type = columns.Text(required=True)
    resource_id = columns.UUID(required=False)
    result = columns.Text(required=True)
    ip = columns.Text(required=False, default="")
    meta = columns.Text(db_field="metadata", required=False, default="")


class AccessAuditByResource(models.Model):
    """Per-resource audit trail ("everything that happened to object X")."""

    __table_name__ = "access_audit_by_resource"
    __keyspace__ = "amigoact"

    resource_id = columns.UUID(primary_key=True, partition_key=True)
    occurred_at = columns.DateTime(primary_key=True, clustering_order="DESC")
    log_id = columns.UUID(
        primary_key=True, clustering_order="ASC", default=uuid7
    )
    org_id = columns.UUID(required=False)
    actor_id = columns.UUID(required=True)
    action = columns.Text(required=True)
    result = columns.Text(required=True)
