"""cqlengine persistence for rbac: roles, assignments, grants, audit."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from rbac.catalog import SYSTEM_ROLES
from rbac.interfaces import (
    AuditReader,
    AuditWriter,
    GrantRepository,
    MemberDefaultsRepository,
    RoleRepository,
)
from rbac.model import (
    AccessAuditByResource,
    AccessAuditLog,
    OrgMemberDefault,
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

    def list_org_roles(self, org_id: UUID) -> list[Role]:
        roles: list[Role] = []
        for link in RolesByOrg.objects(org_id=org_id).all():
            role = self.get_role(link.role_id)
            if role is not None:
                roles.append(role)
        return roles

    def create_org_role(
        self,
        org_id: UUID,
        role_id: UUID,
        name: str,
        description: str,
        now: datetime,
        color: str = "",
        position: int = 0,
    ) -> Role:
        role = Role.create(
            id=role_id,
            org_id=org_id,
            name=name,
            description=description,
            is_system=False,
            created_at=now,
            color=color,
            position=position,
        )
        RolesByOrg.create(org_id=org_id, role_id=role_id, name=name)
        return role

    def update_org_role(
        self,
        org_id: UUID,
        role_id: UUID,
        name: str | None,
        description: str | None,
        color: str | None = None,
    ) -> Role | None:
        role = self.get_role(role_id)
        if role is None or role.org_id != org_id or role.is_system:
            return None
        updates: dict[str, str] = {}
        if color is not None:
            updates["color"] = color
        if name is not None:
            updates["name"] = name
        if description is not None:
            updates["description"] = description
        if not updates:
            return role
        Role.objects(id=role_id).update(**updates)
        if name is not None:
            RolesByOrg.objects(org_id=org_id, role_id=role_id).update(
                name=name
            )
        return self.get_role(role_id)

    def set_role_positions(
        self, org_id: UUID, positions: dict[UUID, int]
    ) -> None:
        for role_id, position in positions.items():
            role = self.get_role(role_id)
            if role is None or role.org_id != org_id or role.is_system:
                continue
            Role.objects(id=role_id).update(position=position)

    def delete_org_role(self, org_id: UUID, role_id: UUID) -> bool:
        role = self.get_role(role_id)
        if role is None or role.org_id != org_id or role.is_system:
            return False
        # Cascade every assignment off both query tables first so no
        # dangling role ids linger on member rows.
        for row in UserRole.objects(org_id=org_id).all():
            if row.role_id != role_id:
                continue
            RolesByUser.objects(
                user_id=row.user_id, org_id=org_id, role_id=role_id
            ).delete()
            UserRole.objects(
                org_id=org_id, user_id=row.user_id, role_id=role_id
            ).delete()
        RolePermission.objects(role_id=role_id).delete()
        RolesByOrg.objects(org_id=org_id, role_id=role_id).delete()
        Role.objects(id=role_id).delete()
        return True

    def set_role_permissions(self, role_id: UUID, codes: set[str]) -> None:
        existing = {
            row.permission_code
            for row in RolePermission.objects(role_id=role_id).all()
        }
        for code in existing - codes:
            RolePermission.objects(
                role_id=role_id, permission_code=code
            ).delete()
        for code in codes - existing:
            RolePermission.create(role_id=role_id, permission_code=code)

    def count_role_holders(self, org_id: UUID) -> dict[UUID, int]:
        counts: dict[UUID, int] = {}
        for row in UserRole.objects(org_id=org_id).all():
            counts[row.role_id] = counts.get(row.role_id, 0) + 1
        return counts


class CqlMemberDefaultsRepository(MemberDefaultsRepository):
    """org_member_defaults rows: the baseline permission set per org."""

    def list_defaults(self, org_id: UUID) -> set[str]:
        return {
            row.permission_code
            for row in OrgMemberDefault.objects(org_id=org_id).all()
        }

    def set_defaults(self, org_id: UUID, codes: set[str]) -> None:
        existing = self.list_defaults(org_id)
        for code in existing - codes:
            OrgMemberDefault.objects(
                org_id=org_id, permission_code=code
            ).delete()
        for code in codes - existing:
            OrgMemberDefault.create(org_id=org_id, permission_code=code)


class CqlGrantRepository(GrantRepository):
    """Direct per-user permission grant rows."""

    def get_grant(
        self, org_id: UUID, user_id: UUID, permission_code: str
    ) -> UserPermissionGrant | None:
        return UserPermissionGrant.objects(
            org_id=org_id, user_id=user_id, permission_code=permission_code
        ).first()

    def list_grants(
        self, org_id: UUID, user_id: UUID
    ) -> list[UserPermissionGrant]:
        return list(
            UserPermissionGrant.objects(
                org_id=org_id, user_id=user_id
            ).all()
        )


class CqlAuditReader(AuditReader):
    """Newest-first reads over the org audit partition."""

    def list_for_org(
        self, org_id: UUID, limit: int
    ) -> list[AccessAuditLog]:
        return list(
            AccessAuditLog.objects(org_id=org_id).limit(limit)
        )


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
        metadata: str | None = None,
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
            meta=metadata,
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
