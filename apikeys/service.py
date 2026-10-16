"""API key issuance, listing, revocation, and authentication."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from apikeys.interfaces import ApiKeyStore
from core.exceptions import ForbiddenError, InvalidCredentialsError, NotFoundError
from core.ids import uuid7
from core.security import expired, hash_token, utcnow
from orgs.interfaces import OrgRepository
from rbac.interfaces import AccessControl

_KEY_PREFIX = "amk_"
_KEY_BYTES = 32


@dataclass(frozen=True)
class IssuedKey:
    """Plaintext secret, returned exactly once at creation."""

    key_id: UUID
    name: str
    api_key: str
    scopes: set[str]
    expires_at: datetime | None


@dataclass(frozen=True)
class KeyView:
    """Safe listing row; never contains secret material."""

    key_id: UUID
    name: str
    scopes: set[str]
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime | None


@dataclass(frozen=True)
class ResolvedKey:
    """Authenticated key identity for downstream permission checks."""

    org_id: UUID
    key_id: UUID
    scopes: set[str]


class ApiKeyService:
    """Issue, list, revoke, and resolve org API keys."""

    def __init__(
        self,
        store: ApiKeyStore,
        orgs: OrgRepository,
        access: AccessControl,
    ) -> None:
        self._store = store
        self._orgs = orgs
        self._access = access

    def _require_manager(self, org_id: UUID, actor_id: UUID) -> None:
        org = self._orgs.get_by_id(org_id)
        if org is None or getattr(org, "deleted_at", None) is not None:
            raise NotFoundError("Organization not found.")
        if org.owner_id != actor_id and not self._access.has_permission(
            org_id, actor_id, "org:update"
        ):
            raise ForbiddenError("Only org managers can manage API keys.")

    def create(
        self,
        org_id: UUID,
        actor_id: UUID,
        name: str,
        scopes: set[str],
        ttl_days: int | None = None,
    ) -> IssuedKey:
        self._require_manager(org_id, actor_id)
        plain = _KEY_PREFIX + secrets.token_urlsafe(_KEY_BYTES)
        expires = (
            utcnow() + timedelta(days=ttl_days) if ttl_days is not None else None
        )
        key_id = uuid7()
        self._store.create(
            key_hash=hash_token(plain),
            key_id=key_id,
            org_id=org_id,
            name=name.strip(),
            scopes=scopes,
            expires_at=expires,
            now=utcnow(),
        )
        return IssuedKey(
            key_id=key_id,
            name=name.strip(),
            api_key=plain,
            scopes=scopes,
            expires_at=expires,
        )

    def list_for_org(self, org_id: UUID, actor_id: UUID) -> list[KeyView]:
        self._require_manager(org_id, actor_id)
        return [
            KeyView(
                key_id=row.key_id,
                name=row.name,
                scopes=set(row.scopes or set()),
                expires_at=row.expires_at,
                revoked_at=row.revoked_at,
                last_used_at=row.last_used_at,
                created_at=row.created_at,
            )
            for row in self._store.list_for_org(org_id)
        ]

    def revoke(self, org_id: UUID, actor_id: UUID, key_id: UUID) -> None:
        self._require_manager(org_id, actor_id)
        self._store.revoke(org_id, key_id, utcnow())

    def resolve(self, presented: str) -> ResolvedKey:
        """Authenticate an X-Api-Key header; raises like bad credentials."""
        if not presented.startswith(_KEY_PREFIX):
            raise InvalidCredentialsError("API key is invalid.")
        row = self._store.get_by_hash(hash_token(presented))
        if (
            row is None
            or row.revoked_at is not None
            or (row.expires_at is not None and expired(row.expires_at))
        ):
            raise InvalidCredentialsError("API key is invalid.")
        self._store.touch(row.key_hash, row.org_id, row.key_id, utcnow())
        return ResolvedKey(
            org_id=row.org_id,
            key_id=row.key_id,
            scopes=set(row.scopes or set()),
        )
