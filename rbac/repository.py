"""cqlengine persistence for rbac: roles, assignments, grants, audit."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from rbac.catalog import SYSTEM_ROLES
from rbac.interfaces import AuditWriter, GrantRepository, RoleRepository
from rbac.model import (
    AccessAuditByResource,
    AccessAuditLog,
    Permission,
    Role,
    RolePermission,
    RolesByOrg,
    RolesByUser,
    UserPermissionGrant,
    UserRole,
)

try:
    from cassandra.cqlengine.query import BatchQuery
except ImportError:  # pragma: no cover - driver without batch support
    BatchQuery = None  # type: ignore[assignment]


class CqlRoleRepository(RoleRepository):
    """Roles plus dual-write assignment tables."""

    def get_role(self, role_id: UUID) -> Role | None:
        return Role.objects(id=role_id).first()

    def resolve_role(self, org_id: UUID, name: str) -> Role | None:
        meta = SYSTEM_ROLES.get(name)
        if meta is not None:
            return self.get_role(meta["id"])  # type: ignore[arg-type]
        for link in RolesByOrg.objects(org_id=org_id).all():
            if link.name == name:
                return self.get_role(link.role_id)
        return None

    def list_role_permissions(self, role_id: UUID) -> set[str]:
        return {
            row.permission_code
            for row in RolePermission.objects(role_id=role_id).all()
        }

    def list_assignments(self, org_id: UUID, user_id: UUID) -> list[UserRole]:
        return list(
            UserRole.objects(org_id=org_id, user_id=user_id).all()
        )

    def list_org_assignments(self, org_id: UUID) -> list[UserRole]:
        return list(UserRole.objects(org_id=org_id).all())

    def assign_role(
        self,
        org_id: UUID,
        user_id: UUID,
        role_id: UUID,
        granted_by: UUID,
        now: datetime,
    ) -> None:
        if BatchQuery is not None:
            # Logged batch keeps both assignment tables in sync atomically.
            with BatchQuery() as batch:
                UserRole.batch(batch).create(
                    org_id=org_id,
                    user_id=user_id,
                    role_id=role_id,
                    granted_by=granted_by,
                    granted_at=now,
                )
                RolesByUser.batch(batch).create(
                    user_id=user_id,
                    org_id=org_id,
                    role_id=role_id,
                    granted_at=now,
                )
            return
        # Fallback without batch: best-effort with compensation.
        # If the second write fails, remove the first to avoid orphan rows.
        UserRole.create(
            org_id=org_id,
            user_id=user_id,
            role_id=role_id,
            granted_by=granted_by,
            granted_at=now,
        )
        try:
            RolesByUser.create(
                user_id=user_id,
                org_id=org_id,
                role_id=role_id,
                granted_at=now,
            )
        except Exception:
            try:
                UserRole.objects(
                    org_id=org_id, user_id=user_id, role_id=role_id
                ).delete()
            except Exception:
                pass
            raise

    def revoke_role(self, org_id: UUID, user_id: UUID, role_id: UUID) -> None:
        if BatchQuery is not None:
            # Logged batch removes both assignment rows atomically.
            with BatchQuery() as batch:
                UserRole.objects(
                    org_id=org_id, user_id=user_id, role_id=role_id
                ).batch(batch).delete()
                RolesByUser.objects(
                    user_id=user_id, org_id=org_id, role_id=role_id
                ).batch(batch).delete()
            return
        # Fallback without batch: best-effort sequential deletes.
        # Deletes are idempotent so a retry converges; no recreate needed.
        UserRole.objects(
            org_id=org_id, user_id=user_id, role_id=role_id
        ).delete()
        try:
            RolesByUser.objects(
                user_id=user_id, org_id=org_id, role_id=role_id
            ).delete()
        except Exception:
            # First table is already cleared; surface the failure so the
            # caller retries the still-pending second delete.
            raise


class CqlGrantRepository(GrantRepository):
    """Direct per-user permission grant rows."""

    def get_grant(
        self, org_id: UUID, user_id: UUID, permission_code: str
    ) -> UserPermissionGrant | None:
        return UserPermissionGrant.objects(
            org_id=org_id, user_id=user_id, permission_code=permission_code
        ).first()


class CqlAuditWriter(AuditWriter):
    """Append-only access_audit_logs writer."""

    def record(
        self,
        org_id: UUID,
        actor_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        result: str,
        now: datetime,
    ) -> None:
        from core.ids import uuid7

        log_id = uuid7()
        AccessAuditLog.create(
            org_id=org_id,
            occurred_at=now,
            log_id=log_id,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            result=result,
        )
        if resource_id is not None:
            AccessAuditByResource.create(
                resource_id=resource_id,
                occurred_at=now,
                log_id=log_id,
                org_id=org_id,
                actor_id=actor_id,
                action=action,
                result=result,
            )
