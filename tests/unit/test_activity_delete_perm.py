"""activity:delete: trash rights without edit rights, umbrella still works."""

from __future__ import annotations

import pytest
import uuid_utils

from core.exceptions import ForbiddenError
from tests.unit.activity_fakes import _fields
from tests.unit.test_activity_delete import _published, _svc, _org_with_owner


def _setup():  # noqa: ANN202
    service, deletes, _, orgs, access = _svc()
    owner, cleaner = uuid_utils.uuid7(), uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    orgs.members[org.id].add(cleaner)
    row = _published(service, orgs, owner, org)
    return service, deletes, access, org, owner, cleaner, row


def test_delete_holder_trashes_and_restores_but_cannot_edit() -> None:
    service, deletes, access, org, _, cleaner, row = _setup()
    with pytest.raises(ForbiddenError):
        deletes.soft_delete(org.id, row.id, cleaner)
    access.perms[(org.id, cleaner)] = {"activity:delete"}
    deletes.soft_delete(org.id, row.id, cleaner)
    assert [r.id for r in service.list_org(org.id, cleaner, trash=True)] == [row.id]
    deletes.restore(org.id, row.id, cleaner)
    with pytest.raises(ForbiddenError):
        service.update_activity(org.id, row.id, cleaner, _fields(None))


def test_manage_umbrella_still_covers_deletion() -> None:
    service, deletes, access, org, _, cleaner, row = _setup()
    access.perms[(org.id, cleaner)] = {"activity:manage"}
    deletes.soft_delete(org.id, row.id, cleaner)
    assert [r.id for r in service.list_org(org.id, cleaner, trash=True)] == [row.id]
