"""cqlengine persistence for platform roles (dual-write)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from admin.interfaces import PlatformRoleStore
from admin.model import PlatformRoleRoster, PlatformUserRole


class CqlPlatformRoleStore(PlatformRoleStore):
    """Both lookup directions stay in sync on every write."""

    def grant(
        self,
        user_id: UUID,
        role_id: UUID,
        granted_by: UUID,
        now: datetime,
    ) -> None:
        PlatformUserRole.create(
            user_id=user_id,
            role_id=role_id,
            granted_by=granted_by,
            granted_at=now,
        )
        PlatformRoleRoster.create(
            role_id=role_id,
            user_id=user_id,
            granted_by=granted_by,
            granted_at=now,
        )

    def revoke(self, user_id: UUID, role_id: UUID) -> None:
        PlatformUserRole.objects(user_id=user_id, role_id=role_id).delete()
        PlatformRoleRoster.objects(role_id=role_id, user_id=user_id).delete()

    def has_role(self, user_id: UUID, role_id: UUID) -> bool:
        row = PlatformUserRole.objects(
            user_id=user_id, role_id=role_id
        ).first()
        if row is None:
            return False
        expires = row.expires_at
        if expires is None:
            return True
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires > datetime.now(timezone.utc)

    def list_holders(self, role_id: UUID) -> list[UUID]:
        return [
            row.user_id
            for row in PlatformRoleRoster.objects(role_id=role_id).all()
        ]
