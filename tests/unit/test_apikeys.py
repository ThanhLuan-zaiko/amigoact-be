"""apikeys: issue, list, revoke, resolve with scope + expiry checks."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from apikeys.interfaces import ApiKeyStore
from apikeys.service import ApiKeyService
from core.exceptions import (
    ForbiddenError,
    InvalidCredentialsError,
    NotFoundError,
)
from core.ids import uuid7
from core.security import hash_token, utcnow
from tests.unit.member_fakes import FakeAccess, FakeOrgs


class FakeApiKeys(ApiKeyStore):
    def __init__(self) -> None:
        self.rows: dict[str, Any] = {}
        self.by_org: dict[UUID, dict[UUID, Any]] = {}

    def create(self, key_hash, key_id, org_id, name, scopes, expires_at, now):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            key_hash=key_hash, key_id=key_id, org_id=org_id, name=name,
            scopes=set(scopes), expires_at=expires_at, revoked_at=None,
            last_used_at=None, created_at=now,
        )
        self.rows[key_hash] = row
        self.by_org.setdefault(org_id, {})[key_id] = row
        return row

    def get_by_hash(self, key_hash):  # noqa: ANN001, ANN202
        return self.rows.get(key_hash)

    def list_for_org(self, org_id):  # noqa: ANN001, ANN202
        return list(self.by_org.get(org_id, {}).values())

    def revoke(self, org_id, key_id, now):  # noqa: ANN001, ANN202
        row = self.by_org.get(org_id, {}).get(key_id)
        if row is not None:
            row.revoked_at = now

    def touch(self, key_hash, org_id, key_id, now):  # noqa: ANN001, ANN202
        row = self.by_org.get(org_id, {}).get(key_id)
        if row is not None:
            row.last_used_at = now


def _setup() -> tuple[ApiKeyService, FakeApiKeys, FakeOrgs, FakeAccess, UUID, UUID]:
    store = FakeApiKeys()
    orgs = FakeOrgs()
    access = FakeAccess()
    owner = uuid7()
    org_id = uuid7()
    orgs.add(org_id, owner)
    service = ApiKeyService(store=store, orgs=orgs, access=access)
    return service, store, orgs, access, org_id, owner


def test_create_returns_plaintext_once() -> None:
    service, store, _, _, org_id, owner = _setup()
    issued = service.create(org_id, owner, "CI bot", {"activities:read"}, 30)
    assert issued.api_key.startswith("amk_")
    row = store.get_by_hash(hash_token(issued.api_key))
    assert row is not None and row.name == "CI bot"
    assert row.expires_at is not None


def test_list_and_revoke() -> None:
    service, _, _, _, org_id, owner = _setup()
    issued = service.create(org_id, owner, "Hook", set(), None)
    views = service.list_for_org(org_id, owner)
    assert len(views) == 1 and views[0].key_id == issued.key_id
    service.revoke(org_id, owner, issued.key_id)
    assert service.list_for_org(org_id, owner)[0].revoked_at is not None


def test_resolve_valid_and_touch() -> None:
    service, _, _, _, org_id, owner = _setup()
    issued = service.create(org_id, owner, "Bot", {"stats:read"}, None)
    resolved = service.resolve(issued.api_key)
    assert resolved.org_id == org_id and resolved.scopes == {"stats:read"}
    row = service._store.get_by_hash(hash_token(issued.api_key))
    assert row.last_used_at is not None


def test_resolve_rejects_garbage_and_revoked() -> None:
    service, _, _, _, org_id, owner = _setup()
    issued = service.create(org_id, owner, "Bot", set(), None)
    with pytest.raises(InvalidCredentialsError):
        service.resolve("amk_wrong_wrong_wrong")
    with pytest.raises(InvalidCredentialsError):
        service.resolve("not-a-key")
    service.revoke(org_id, owner, issued.key_id)
    with pytest.raises(InvalidCredentialsError):
        service.resolve(issued.api_key)


def test_non_manager_cannot_manage() -> None:
    service, _, orgs, access, org_id, _ = _setup()
    outsider = uuid7()
    with pytest.raises(ForbiddenError):
        service.create(org_id, outsider, "X", set(), None)
    access.perms[(org_id, outsider)] = {"org:update"}
    issued = service.create(org_id, outsider, "X", set(), None)
    assert issued.api_key


def test_missing_org_404() -> None:
    service, _, _, _, _, owner = _setup()
    with pytest.raises(NotFoundError):
        service.create(uuid7(), owner, "X", set(), None)
