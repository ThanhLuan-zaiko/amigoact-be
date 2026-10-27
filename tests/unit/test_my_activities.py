"""Unit tests for the cross-org activity feed (MyActivitiesService)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import uuid_utils

from activities import mine_service
from activities.mine_service import MyActivitiesService
from orgs.brand import brand_url
from tests.unit.activity_fakes import FakeActivities, _fields
from tests.unit.member_fakes import FakeAccess, FakeOrgs
from tests.unit.org_fakes import FakeMedia

NOW = datetime.now(UTC)


class _UserOrgs(FakeOrgs):
    """FakeOrgs with a membership index so list_by_user means something."""

    def __init__(self) -> None:
        super().__init__()
        self.memberships: dict[UUID, list[UUID]] = {}

    def join(self, user_id: UUID, org_id: UUID) -> None:
        self.memberships.setdefault(user_id, []).append(org_id)

    def list_by_user(self, user_id):  # noqa: ANN001, ANN202
        return [
            self.orgs[org_id]
            for org_id in self.memberships.get(user_id, [])
            if org_id in self.orgs
        ]


def _world(media: FakeMedia | None = None):
    orgs, activities, access = _UserOrgs(), FakeActivities(), FakeAccess()
    service = MyActivitiesService(orgs, activities, access, media)
    return service, orgs, activities, access


def _org(orgs: _UserOrgs, owner: UUID) -> UUID:
    org_id = uuid_utils.uuid7()
    orgs.add(org_id, owner)
    return org_id


def _activity(
    activities: FakeActivities,
    org_id: UUID,
    creator: UUID,
    title: str = "Run",
    days: int = 7,
    trashed: bool = False,
):
    fields = _fields(
        None,
        title=title,
        slug=str(uuid_utils.uuid7()),
        start_at=NOW + timedelta(days=days),
    )
    row = activities.create(org_id, creator, fields, NOW)
    if trashed:
        activities.mark_deleted(row.id, NOW)
    return row


def test_feed_lists_only_orgs_the_caller_joined() -> None:
    service, orgs, activities, _ = _world()
    owner, user = uuid_utils.uuid7(), uuid_utils.uuid7()
    mine = _org(orgs, owner)
    other = _org(orgs, owner)
    orgs.join(user, mine)
    _activity(activities, mine, owner, title="Mine")
    _activity(activities, other, owner, title="Other")
    feed = service.feed(user)
    assert [grant.org.id for grant in feed.orgs] == [mine]
    assert [item.activity.title for item in feed.rows] == ["Mine"]


def test_grants_follow_owner_and_permissions() -> None:
    service, orgs, activities, access = _world()
    owner, manager, creator = (uuid_utils.uuid7() for _ in range(3))
    org = _org(orgs, owner)
    for user in (owner, manager, creator):
        orgs.join(user, org)
    access.perms[(org, manager)] = {"activity:manage"}
    access.perms[(org, creator)] = {"activity:create"}
    _activity(activities, org, owner)
    grants = {
        user: (service.feed(user).orgs[0].can_create, service.feed(user).orgs[0].can_manage)
        for user in (owner, manager, creator)
    }
    assert grants[owner] == (True, True)
    assert grants[manager] == (False, True)
    assert grants[creator] == (True, False)
    assert service.feed(creator).rows[0].can_manage is False
    assert service.feed(manager).rows[0].can_manage is True


def test_soft_deleted_org_is_hidden() -> None:
    service, orgs, activities, _ = _world()
    owner = uuid_utils.uuid7()
    org = _org(orgs, owner)
    orgs.join(owner, org)
    _activity(activities, org, owner)
    orgs.orgs[org].deleted_at = NOW
    feed = service.feed(owner)
    assert feed.orgs == []
    assert feed.rows == []


def test_trash_is_limited_to_orgs_the_caller_manages() -> None:
    service, orgs, activities, _ = _world()
    owner, member = uuid_utils.uuid7(), uuid_utils.uuid7()
    managed = _org(orgs, owner)
    shared = _org(orgs, owner)
    orgs.join(owner, managed)
    orgs.join(owner, shared)
    orgs.join(member, shared)
    _activity(activities, managed, owner, title="Kept")
    _activity(activities, managed, owner, title="Gone", trashed=True)

    live = service.feed(owner)
    assert [item.activity.title for item in live.rows] == ["Kept"]

    owner_trash = service.feed(owner, trash=True)
    assert [item.activity.title for item in owner_trash.rows] == ["Gone"]
    assert [grant.org.id for grant in owner_trash.orgs] == [managed, shared]

    member_trash = service.feed(member, trash=True)
    assert member_trash.orgs == []
    assert member_trash.rows == []


def test_rows_are_sorted_soonest_first() -> None:
    service, orgs, activities, _ = _world()
    owner = uuid_utils.uuid7()
    org = _org(orgs, owner)
    orgs.join(owner, org)
    _activity(activities, org, owner, title="Later", days=9)
    _activity(activities, org, owner, title="Sooner", days=2)
    feed = service.feed(owner)
    assert [item.activity.title for item in feed.rows] == ["Sooner", "Later"]


def test_feed_is_capped_at_the_page_limit(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(mine_service, "FEED_LIMIT", 2)
    service, orgs, activities, _ = _world()
    owner = uuid_utils.uuid7()
    org = _org(orgs, owner)
    orgs.join(owner, org)
    for days in (1, 2, 3):
        _activity(activities, org, owner, days=days)
    assert len(service.feed(owner).rows) == 2


def test_org_logo_resolves_only_from_its_own_logo_asset() -> None:
    media = FakeMedia()
    service, orgs, _, _ = _world(media)
    owner = uuid_utils.uuid7()
    org = _org(orgs, owner)
    other = _org(orgs, owner)
    orgs.join(owner, org)
    logo, cover = uuid_utils.uuid7(), uuid_utils.uuid7()
    media.create_asset(
        logo, org, "orgs/own/logo.png", "image/png", 10, NOW,
        role="logo", owner_type="organization", owner_feed=False,
    )
    media.create_asset(
        cover, org, "orgs/own/cover.png", "image/png", 10, NOW,
        role="cover", owner_type="organization", owner_feed=False,
    )
    orgs.orgs[org].logo_media_id = logo
    assert service.feed(owner).orgs[0].logo_url == "/media/orgs/own/logo.png"
    # A cover asset in the logo slot is not a logo.
    orgs.orgs[org].logo_media_id = cover
    assert service.feed(owner).orgs[0].logo_url is None
    # Another org's asset never resolves, even if pointed at.
    assert brand_url(media, other, logo, "logo") is None


def test_delete_holder_sees_trash_without_manage_right() -> None:
    service, orgs, activities, access = _world()
    owner, cleaner = uuid_utils.uuid7(), uuid_utils.uuid7()
    org_id = _org(orgs, owner)
    orgs.join(cleaner, org_id)
    _activity(activities, org_id, owner, title="Old", trashed=True)
    access.perms[(org_id, cleaner)] = {"activity:delete"}
    feed = service.feed(cleaner, trash=True)
    assert [row.activity.title for row in feed.rows] == ["Old"]
    grant = feed.orgs[0]
    assert (grant.can_manage, grant.can_delete) == (False, True)
    assert feed.rows[0].can_delete is True

