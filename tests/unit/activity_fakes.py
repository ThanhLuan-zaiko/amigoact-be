"""Shared in-memory ports for ActivityService unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import uuid_utils

from activities.detail_service import ActivityDetailService
from activities.interfaces import (
    ActivityEvents,
    ActivityStore,
    CategoryStore,
)
from activities.model import tag_slug
from activities.service import ActivityService
from activities.tag_service import TagService
from tests.unit.edge_fakes import (
    FakeAnnouncements,
    FakeLinks,
    FakeSchedules,
    FakeStaff,
)
from tests.unit.member_fakes import FakeAccess, FakeUsers
from tests.unit.org_fakes import FakeOrgs
from tests.unit.profile_fakes import FakeProfiles
from tests.unit.tag_fakes import FakeOrgTags


class FakeActivities(ActivityStore):
    def __init__(self) -> None:
        self.rows: dict[UUID, Any] = {}

    def create(self, org_id, created_by, fields, now):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            id=uuid_utils.uuid7(), org_id=org_id, created_by=created_by,
            status="draft", published_at=None, deleted_at=None,
            cover_media_id=None, created_at=now, updated_at=now,
            **{k: getattr(fields, k) for k in vars(fields)},
        )
        self.rows[row.id] = row
        return row

    def get(self, activity_id):  # noqa: ANN001, ANN202
        return self.rows.get(activity_id)

    def get_by_slug(self, org_id, slug):  # noqa: ANN001, ANN202
        for row in self.rows.values():
            if row.org_id == org_id and row.slug == slug:
                return SimpleNamespace(activity_id=row.id)
        return None

    def update_details(self, activity_id, fields, now):  # noqa: ANN001, ANN202
        row = self.rows.get(activity_id)
        if row is None:
            return None
        for key in vars(fields):
            setattr(row, key, getattr(fields, key))
        row.updated_at = now
        return row

    def set_status(self, activity_id, status, published_at, now):  # noqa: ANN001, ANN202
        row = self.rows.get(activity_id)
        if row is None:
            return None
        row.status = status
        if published_at is not None:
            row.published_at = published_at
        row.updated_at = now
        return row

    def list_by_org(self, org_id, limit=50):  # noqa: ANN001, ANN202
        return [
            r for r in self.rows.values()
            if r.org_id == org_id and r.deleted_at is None
        ][:limit]

    def list_by_status(self, status, limit=50):  # noqa: ANN001, ANN202
        return [
            r for r in self.rows.values()
            if r.status == status and r.deleted_at is None
        ][:limit]

    def list_by_category(self, category_id, limit=50):  # noqa: ANN001, ANN202
        return [
            r for r in self.rows.values()
            if r.category_id == category_id and r.deleted_at is None
        ][:limit]

    def list_by_tag(self, slug, limit=50):  # noqa: ANN001, ANN202
        return [
            r
            for r in self.rows.values()
            if r.deleted_at is None
            and slug in {tag_slug(n) for n in (r.tag_names or [])}
        ][:limit]

    def mark_deleted(self, activity_id, now):  # noqa: ANN001, ANN202
        row = self.rows.get(activity_id)
        if row is None:
            return None
        row.deleted_at = now
        row.updated_at = now
        return row

    def mark_restored(self, activity_id, now):  # noqa: ANN001, ANN202
        row = self.rows.get(activity_id)
        if row is None:
            return None
        row.deleted_at = None
        row.updated_at = now
        return row

    def list_trash(self, org_id, limit=50):  # noqa: ANN001, ANN202
        return [
            r for r in self.rows.values()
            if r.org_id == org_id and r.deleted_at is not None
        ][:limit]

    def delete_everything(self, activity_id):  # noqa: ANN001, ANN202
        self.rows.pop(activity_id, None)
        return []


class FakeCategories(CategoryStore):
    def __init__(self) -> None:
        self.rows: dict[UUID, Any] = {}

    def seed(self, name, slug, org_id=None):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            id=uuid_utils.uuid7(), org_id=org_id, name=name, slug=slug,
            description=None, icon=None, default_hours=None, color=None,
        )
        self.rows[row.id] = row
        return row

    def get(self, category_id):  # noqa: ANN001, ANN202
        return self.rows.get(category_id)

    def list(self, org_id):  # noqa: ANN001, ANN202
        return [
            r for r in self.rows.values()
            if r.org_id is None or r.org_id == org_id
        ]

    def create(self, category_id, org_id, name, slug, description, icon, default_hours, color):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            id=category_id, org_id=org_id, name=name, slug=slug,
            description=description, icon=icon,
            default_hours=default_hours, color=color,
        )
        self.rows[category_id] = row
        return row


class FakeActivityEvents(ActivityEvents):
    """Captures live activity and tag events instead of publishing."""

    def __init__(self) -> None:
        self.sent: list[tuple] = []
        self.tag_events: list[tuple] = []

    def activity_changed(self, org_id, action, activity_id, actor_id, status):  # noqa: ANN001, ANN202
        self.sent.append((org_id, action, activity_id, actor_id, status))

    def tags_changed(self, org_id, action, slug, actor_id):  # noqa: ANN001, ANN202
        self.tag_events.append((org_id, action, slug, actor_id))


def make_services() -> tuple[
    ActivityService, ActivityDetailService,
    FakeActivities, FakeOrgs, FakeAccess, FakeCategories,
    FakeUsers, FakeProfiles,
]:
    activities = FakeActivities()
    categories = FakeCategories()
    orgs = FakeOrgs()
    access = FakeAccess()
    users = FakeUsers()
    skills = FakeProfiles()
    detail = ActivityDetailService(
        activities=activities,
        links=FakeLinks(),
        staff=FakeStaff(),
        schedules=FakeSchedules(),
        announcements=FakeAnnouncements(),
        orgs=orgs,
        users=users,
        skills=skills,
        access=access,
    )
    service = ActivityService(
        activities=activities,
        categories=categories,
        orgs=orgs,
        access=access,
        tags=TagService(FakeOrgTags(activities)),
    )
    return service, detail, activities, orgs, access, categories, users, skills


def _fields(service: Any, **overrides: Any) -> Any:
    """Build an ActivityFields bag with defaults overridable."""
    from activities.interfaces import ActivityFields
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    defaults = dict(
        title="Beach Cleanup", slug=None, description="",
        category_id=None, location="Vung Tau", address=None,
        city="VT", latitude=None, longitude=None, is_remote=False,
        max_participants=None, start_at=now + timedelta(days=7),
        end_at=None, hours_awarded=4.0, requirements_json=None,
        registration_deadline=None, person_in_charge_id=None,
        tag_names=[],
    )
    defaults.update(overrides)
    if defaults["slug"] is None:
        defaults["slug"] = "beach-cleanup"
    return ActivityFields(**defaults)


def _org_with_owner(orgs: FakeOrgs, owner: UUID, slug: str = "club"):
    from datetime import UTC, datetime

    return orgs.create(
        uuid_utils.uuid7(), owner, "Club", slug, "", "club",
        "open", None, None, None, None, "none",
        datetime.now(UTC),
    )
