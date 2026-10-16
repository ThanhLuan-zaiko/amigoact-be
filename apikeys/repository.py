"""cqlengine persistence for api_keys."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from apikeys.interfaces import ApiKeyStore
from apikeys.model import ApiKey, ApiKeyByOrg


class CqlApiKeyStore(ApiKeyStore):
    """Dual-write api_keys + api_keys_by_org."""

    def create(
        self,
        key_hash: str,
        key_id: UUID,
        org_id: UUID,
        name: str,
        scopes: set[str],
        expires_at: datetime | None,
        now: datetime,
    ) -> ApiKey:
        row = ApiKey.create(
            key_hash=key_hash,
            key_id=key_id,
            org_id=org_id,
            name=name,
            scopes=scopes,
            expires_at=expires_at,
            created_at=now,
        )
        ApiKeyByOrg.create(
            org_id=org_id,
            key_id=key_id,
            key_hash=key_hash,
            name=name,
            scopes=scopes,
            expires_at=expires_at,
            created_at=now,
        )
        return row

    def get_by_hash(self, key_hash: str) -> ApiKey | None:
        return ApiKey.objects(key_hash=key_hash).first()

    def list_for_org(self, org_id: UUID) -> list[ApiKeyByOrg]:
        return list(ApiKeyByOrg.objects(org_id=org_id).all())

    def revoke(self, org_id: UUID, key_id: UUID, now: datetime) -> None:
        row = ApiKeyByOrg.objects(org_id=org_id, key_id=key_id).first()
        if row is None:
            return
        ApiKeyByOrg.objects(org_id=org_id, key_id=key_id).update(revoked_at=now)
        ApiKey.objects(key_hash=row.key_hash).update(revoked_at=now)

    def touch(self, key_hash: str, org_id: UUID, key_id: UUID, now: datetime) -> None:
        ApiKey.objects(key_hash=key_hash).update(last_used_at=now)
        ApiKeyByOrg.objects(org_id=org_id, key_id=key_id).update(
            last_used_at=now
        )
