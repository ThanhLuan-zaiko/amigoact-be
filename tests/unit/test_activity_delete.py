"""Unit tests for the activity trash lifecycle (soft/restore/purge)."""

from __future__ import annotations

import pytest
import uuid_utils

from activities.delete_service import ActivityDeleteService
from core.exceptions import (
    ActivityDeletedError,
    ForbiddenError,
    InvalidOrgStateError,
    NotFoundError,
)
from tests.unit.activity_fakes import (
    _fields,
    _org_with_owner,
    make_services,
)


def _svc():
    """make_services plus a delete service over the same fakes."""
    service, _, activities, orgs, access, *_ = make_services()
    deletes = ActivityDeleteService(
        activities=activities, orgs=orgs, access=access
    )
    return service, deletes, activities, orgs, access


def _published(service, orgs, owner, org, slug=None):  # noqa: ANN001, ANN202
    row = service.create_activity(org.id, owner, _fields(None, slug=slug))
    service.set_status(org.id, row.id, owner, "published")
    return row


def test_soft_delete_hides_and_keeps_row() -> None:
    service, deletes, activities, orgs, _ = _svc()
    owner, member = uuid_utils.uuid7(), uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    orgs.members[org.id].add(member)
    row = _published(service, orgs, owner, org)

    trashed = deletes.soft_delete(org.id, row.id, owner)
    assert trashed.deleted_at is not None
    assert activities.get(row.id) is not None

    assert [r.id for r in service.list_org(org.id, member)] == []
    assert [r.id for r in service.list_org(org.id, owner, trash=True)] == [
        row.id
    ]
    assert [r.id for r in service.list_public("published")] == []
    with pytest.raises(NotFoundError):
        service.get_visible(row.id, None)


def test_soft_delete_blocks_mutations() -> None:
    service, deletes, _, orgs, _ = _svc()
    owner = uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    row = _published(service, orgs, owner, org)
    deletes.soft_delete(org.id, row.id, owner)

    with pytest.raises(ActivityDeletedError):
        service.update_activity(org.id, row.id, owner, _fields(None))
    with pytest.raises(ActivityDeletedError):
        service.set_status(org.id, row.id, owner, "ongoing")
    with pytest.raises(ActivityDeletedError):
        deletes.soft_delete(org.id, row.id, owner)


def test_restore_returns_visibility() -> None:
    service, deletes, _, orgs, _ = _svc()
    owner, member = uuid_utils.uuid7(), uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    orgs.members[org.id].add(member)
    row = _published(service, orgs, owner, org)
    deletes.soft_delete(org.id, row.id, owner)

    restored = deletes.restore(org.id, row.id, owner)
    assert restored.deleted_at is None
    assert [r.id for r in service.list_org(org.id, member)] == [row.id]
    assert service.list_org(org.id, owner, trash=True) == []
    assert service.get_visible(row.id, None).id == row.id

    with pytest.raises(InvalidOrgStateError):
        deletes.restore(org.id, row.id, owner)


def test_hard_delete_purges_row() -> None:
    service, deletes, activities, orgs, _ = _svc()
    owner, member = uuid_utils.uuid7(), uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    orgs.members[org.id].add(member)
    row = _published(service, orgs, owner, org)

    deletes.hard_delete(org.id, row.id, owner)
    assert activities.get(row.id) is None
    assert service.list_org(org.id, member) == []
    assert service.list_org(org.id, owner, trash=True) == []
    with pytest.raises(NotFoundError):
        service.get_visible(row.id, None)


def test_hard_delete_of_trashed_activity() -> None:
    service, deletes, activities, orgs, _ = _svc()
    owner = uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    row = _published(service, orgs, owner, org)
    deletes.soft_delete(org.id, row.id, owner)

    deletes.hard_delete(org.id, row.id, owner)
    assert activities.get(row.id) is None


def test_delete_requires_manager() -> None:
    service, deletes, _, orgs, _ = _svc()
    owner, outsider = uuid_utils.uuid7(), uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    row = _published(service, orgs, owner, org)

    with pytest.raises(ForbiddenError):
        deletes.soft_delete(org.id, row.id, outsider)
    with pytest.raises(ForbiddenError):
        deletes.hard_delete(org.id, row.id, outsider)
    deletes.soft_delete(org.id, row.id, owner)
    with pytest.raises(ForbiddenError):
        deletes.restore(org.id, row.id, outsider)


def test_trash_list_is_manager_only() -> None:
    service, deletes, _, orgs, access = _svc()
    owner, member = uuid_utils.uuid7(), uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    orgs.members[org.id].add(member)
    row = _published(service, orgs, owner, org)
    deletes.soft_delete(org.id, row.id, owner)

    with pytest.raises(ForbiddenError):
        service.list_org(org.id, member, trash=True)
    access.perms[(org.id, member)] = {"activity:manage"}
    assert [r.id for r in service.list_org(org.id, member, trash=True)] == [
        row.id
    ]


def test_cross_org_delete_is_404() -> None:
    service, deletes, _, orgs, _ = _svc()
    owner = uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    other = _org_with_owner(orgs, owner, slug="other-org")
    row = _published(service, orgs, owner, org)

    with pytest.raises(NotFoundError):
        deletes.soft_delete(other.id, row.id, owner)
