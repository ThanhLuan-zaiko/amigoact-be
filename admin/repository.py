"""cqlengine persistence for platform roles (dual-write)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from admin.interfaces import ModerationStore, PlatformRoleStore
from admin.model import MediaModeration, PlatformRoleRoster, PlatformUserRole


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


class CqlModerationStore(ModerationStore):
    """Status-bucketed moderation rows; moves delete + reinsert."""

    def enqueue(
        self,
        moderation_id: UUID,
        asset_id: UUID,
        now: datetime,
    ) -> MediaModeration:
        return MediaModeration.create(
            status="pending",
            created_at=now,
            moderation_id=moderation_id,
            asset_id=asset_id,
        )

    def list_by_status(
        self, status: str, limit: int = 50
    ) -> list[MediaModeration]:
        return list(
            MediaModeration.objects(status=status).limit(limit).all()
        )

    def mark(
        self,
        from_status: str,
        created_at: datetime,
        moderation_id: UUID,
        to_status: str,
        reviewed_by: UUID,
        note: str | None,
        now: datetime,
    ) -> MediaModeration | None:
        row = MediaModeration.objects(
            status=from_status,
            created_at=created_at,
            moderation_id=moderation_id,
        ).first()
        if row is None:
            return None
        MediaModeration.objects(
            status=from_status,
            created_at=created_at,
            moderation_id=moderation_id,
        ).delete()
        return MediaModeration.create(
            status=to_status,
            created_at=row.created_at,
            moderation_id=moderation_id,
            asset_id=row.asset_id,
            reviewed_by=reviewed_by,
            note=note,
        )
