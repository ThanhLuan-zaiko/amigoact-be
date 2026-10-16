"""ActivityMediaService unit tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
import uuid_utils

from activities.interfaces import ActivityMediaStore
from activities.media_service import ActivityMediaService
from core.exceptions import (
    ForbiddenError,
    InvalidMediaRoleError,
    NotFoundError,
)
from tests.unit.member_fakes import FakeAccess
from tests.unit.org_fakes import FakeMedia, FakeOrgs, FakeStore
from tests.unit.registration_fakes import FakeActivities, published_activity


class FakeEntries(ActivityMediaStore):
    def __init__(self) -> None:
        self.rows: dict = {}

    def list_for_activity(self, activity_id):
        rows = [r for r in self.rows.values() if r.activity_id == activity_id]
        return sorted(rows, key=lambda r: r.position)

    def create(self, activity_id, position, asset_id, role, caption):
        from types import SimpleNamespace

        row = SimpleNamespace(
            activity_id=activity_id, position=position,
            asset_id=asset_id, role=role, caption=caption,
        )
        self.rows[(activity_id, position, asset_id)] = row
        return row

    def update(self, activity_id, position, asset_id, caption, role):
        row = self.rows[(activity_id, position, asset_id)]
        row.caption, row.role = caption, role

    def delete(self, activity_id, position, asset_id):
        self.rows.pop((activity_id, position, asset_id), None)


def _svc():
    activities = FakeActivities()
    orgs = FakeOrgs()
    media = FakeMedia()
    entries = FakeEntries()
    store = FakeStore()
    access = FakeAccess()
    service = ActivityMediaService(
        activities=activities, orgs=orgs, media=media,
        entries=entries, store=store, access=access,
        max_image_bytes=5 * 1024 * 1024, max_video_bytes=50 * 1024 * 1024,
    )
    return service, activities, orgs, media, entries, store


def _org(orgs: FakeOrgs, owner: UUID):
    return orgs.create(
        uuid_utils.uuid7(), owner, "Club", "club", "", "club",
        "open", None, None, None, None, "none", datetime.now(UTC),
    )


def test_manager_uploads_and_lists_gallery():
    service, activities, orgs, media, entries, store = _svc()
    owner = uuid_utils.uuid7()
    org = _org(orgs, owner)
    act = published_activity(activities, org.id, owner)

    item = service.upload(
        act.id, owner, "a.png", "image/png", b"png-bytes", "\u1ea2nh 1"
    )
    assert item.kind == "image" and item.caption == "\u1ea2nh 1"
    item2 = service.upload(
        act.id, owner, "b.mp4", "video/mp4", b"v" * 10, None
    )
    assert item2.position == 1
    rows = service.list_media(act.id, None)
    assert len(rows) == 2
    assert media.assets[item.asset_id].owner_type == "activity"
    assert store.files[item.file_url] == b"png-bytes"


def test_upload_requires_manager():
    service, activities, orgs, *_ = _svc()
    owner, other = uuid_utils.uuid7(), uuid_utils.uuid7()
    org = _org(orgs, owner)
    act = published_activity(activities, org.id, owner)
    with pytest.raises(ForbiddenError):
        service.upload(act.id, other, "a.png", "image/png", b"x", None)


def test_bad_role_rejected():
    service, activities, orgs, *_ = _svc()
    owner = uuid_utils.uuid7()
    org = _org(orgs, owner)
    act = published_activity(activities, org.id, owner)
    with pytest.raises(InvalidMediaRoleError):
        service.upload(
            act.id, owner, "a.png", "image/png", b"x", None, role="hero"
        )


def test_update_and_delete_entry():
    service, activities, orgs, media, entries, store = _svc()
    owner = uuid_utils.uuid7()
    org = _org(orgs, owner)
    act = published_activity(activities, org.id, owner)
    item = service.upload(
        act.id, owner, "a.png", "image/png", b"x", "old"
    )
    updated = service.update_entry(
        act.id, owner, item.asset_id, "new", "cover"
    )
    assert updated.caption == "new" and updated.role == "cover"

    service.delete(act.id, owner, item.asset_id)
    assert service.list_media(act.id, None) == []
    assert item.asset_id not in media.assets
    with pytest.raises(NotFoundError):
        service.delete(act.id, owner, item.asset_id)
