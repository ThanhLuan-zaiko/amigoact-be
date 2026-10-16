"""Unit tests for ActivityService lifecycle and visibility rules."""

from __future__ import annotations

import uuid_utils
import pytest

from core.exceptions import (
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
    return make_services()


def test_owner_creates_draft() -> None:
    service, _, activities, orgs, *_ = _svc()
    owner = uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    row = service.create_activity(org.id, owner, _fields(None))
    assert row.status == "draft"
    assert row.org_id == org.id
    assert row.slug == "beach-cleanup"


def test_non_manager_cannot_create() -> None:
    service, _, _, orgs, *_ = _svc()
    owner, outsider = uuid_utils.uuid7(), uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    with pytest.raises(ForbiddenError):
        service.create_activity(org.id, outsider, _fields(None))


def test_permitted_member_creates() -> None:
    service, _, _, orgs, access, *_ = _svc()
    owner, member = uuid_utils.uuid7(), uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    access.perms[(org.id, member)] = {"activity:create"}
    row = service.create_activity(org.id, member, _fields(None))
    assert row.created_by == member


def test_lifecycle_edges() -> None:
    service, _, _, orgs, *_ = _svc()
    owner = uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    row = service.create_activity(org.id, owner, _fields(None))
    with pytest.raises(InvalidOrgStateError):
        service.set_status(org.id, row.id, owner, "completed")
    row = service.set_status(org.id, row.id, owner, "published")
    assert row.published_at is not None
    row = service.set_status(org.id, row.id, owner, "ongoing")
    row = service.set_status(org.id, row.id, owner, "completed")
    with pytest.raises(InvalidOrgStateError):
        service.set_status(org.id, row.id, owner, "cancelled")
    with pytest.raises(InvalidOrgStateError):
        service.update_activity(org.id, row.id, owner, _fields(None))


def test_lifecycle_publishes_activity_events() -> None:
    """Committed create/update/transition fan out on activities:{org}."""
    from activities.service import ActivityService
    from tests.unit.activity_fakes import (
        FakeActivities,
        FakeActivityEvents,
        FakeCategories,
    )
    from tests.unit.member_fakes import FakeAccess
    from tests.unit.org_fakes import FakeOrgs

    events = FakeActivityEvents()
    activities, orgs = FakeActivities(), FakeOrgs()
    service = ActivityService(
        activities=activities, categories=FakeCategories(),
        orgs=orgs, access=FakeAccess(), events=events,
    )
    owner = uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    row = service.create_activity(org.id, owner, _fields(None))
    assert events.sent == [
        (org.id, "created", row.id, owner, "draft")
    ]
    service.update_activity(org.id, row.id, owner, _fields(None))
    assert events.sent[-1] == (
        org.id, "updated", row.id, owner, "draft"
    )
    service.set_status(org.id, row.id, owner, "published")
    assert events.sent[-1] == (
        org.id, "published", row.id, owner, "published"
    )


def test_failed_lifecycle_publishes_nothing() -> None:
    """Rejected mutations must never emit a live event."""
    from activities.service import ActivityService
    from tests.unit.activity_fakes import (
        FakeActivities,
        FakeActivityEvents,
        FakeCategories,
    )
    from tests.unit.member_fakes import FakeAccess
    from tests.unit.org_fakes import FakeOrgs

    events = FakeActivityEvents()
    activities, orgs = FakeActivities(), FakeOrgs()
    service = ActivityService(
        activities=activities, categories=FakeCategories(),
        orgs=orgs, access=FakeAccess(), events=events,
    )
    owner, outsider = uuid_utils.uuid7(), uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    with pytest.raises(ForbiddenError):
        service.create_activity(org.id, outsider, _fields(None))
    row = service.create_activity(org.id, owner, _fields(None))
    with pytest.raises(InvalidOrgStateError):
        service.set_status(org.id, row.id, owner, "completed")
    assert [e[1] for e in events.sent] == ["created"]


def test_draft_visibility_members_only() -> None:
    service, _, _, orgs, *_ = _svc()
    owner, member, anon = (
        uuid_utils.uuid7(),
        uuid_utils.uuid7(),
        uuid_utils.uuid7(),
    )
    org = _org_with_owner(orgs, owner)
    orgs.members[org.id].add(member)
    row = service.create_activity(org.id, owner, _fields(None))
    with pytest.raises(NotFoundError):
        service.get_visible(row.id, None)
    with pytest.raises(NotFoundError):
        service.get_visible(row.id, anon)
    assert service.get_visible(row.id, member).id == row.id
    service.set_status(org.id, row.id, owner, "published")
    assert service.get_visible(row.id, None).id == row.id


def test_slug_lookup_and_cross_org_guard() -> None:
    service, _, _, orgs, *_ = _svc()
    owner = uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    other = _org_with_owner(orgs, owner, slug="other")
    row = service.create_activity(org.id, owner, _fields(None))
    found = service.get_by_slug(org.id, "beach-cleanup", owner)
    assert found.id == row.id
    with pytest.raises(NotFoundError):
        service.get_by_slug(other.id, "beach-cleanup", None)
    with pytest.raises(NotFoundError):
        service.update_activity(other.id, row.id, owner, _fields(None))


def test_list_public_status_filter() -> None:
    service, _, _, orgs, *_ = _svc()
    owner = uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    row = service.create_activity(org.id, owner, _fields(None))
    with pytest.raises(InvalidOrgStateError):
        service.list_public("draft")
    assert service.list_public("published") == []
    service.set_status(org.id, row.id, owner, "published")
    assert len(service.list_public("published")) == 1


def test_org_list_requires_membership() -> None:
    service, _, _, orgs, *_ = _svc()
    owner, member = uuid_utils.uuid7(), uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    service.create_activity(org.id, owner, _fields(None))
    with pytest.raises(ForbiddenError):
        service.list_org(org.id, member)
    orgs.members[org.id].add(member)
    assert len(service.list_org(org.id, member)) == 1


def test_category_scoping() -> None:
    service, _, _, orgs, _, categories, *_ = _svc()
    owner, member = uuid_utils.uuid7(), uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    global_cat = categories.seed("Environment", "environment")
    org_cat = categories.seed("Club Fest", "club-fest", org.id)

    anon = service.list_categories(org.id, None)
    assert {c.slug for c in anon} == {"environment"}
    orgs.members[org.id].add(member)
    scoped = service.list_categories(org.id, member)
    assert {c.slug for c in scoped} == {"environment", "club-fest"}

    with pytest.raises(NotFoundError):
        service.create_activity(
            org.id, owner, _fields(None, category_id=uuid_utils.uuid7())
        )
    row = service.create_activity(
        org.id, owner, _fields(None, category_id=global_cat.id)
    )
    assert row.category_id == global_cat.id

    other = _org_with_owner(orgs, owner, slug="other2")
    with pytest.raises(NotFoundError):
        service.create_activity(
            other.id, owner, _fields(None, category_id=org_cat.id)
        )


def test_update_category_scoping() -> None:
    """Updates must apply the same category existence/scope check."""
    service, _, _, orgs, _, categories, *_ = _svc()
    owner = uuid_utils.uuid7()
    org = _org_with_owner(orgs, owner)
    other = _org_with_owner(orgs, owner, slug="other2")
    foreign = categories.seed("Club Fest", "club-fest", other.id)
    row = service.create_activity(org.id, owner, _fields(None))
    with pytest.raises(NotFoundError):
        service.update_activity(
            org.id,
            row.id,
            owner,
            _fields(None, category_id=uuid_utils.uuid7()),
        )
    with pytest.raises(NotFoundError):
        service.update_activity(
            org.id, row.id, owner, _fields(None, category_id=foreign.id)
        )
    global_cat = categories.seed("Environment", "environment")
    updated = service.update_activity(
        org.id, row.id, owner, _fields(None, category_id=global_cat.id)
    )
    assert updated.category_id == global_cat.id
