"""Shared in-memory ports for ActivityService unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import uuid_utils

from activities.detail_service import ActivityDetailService
from activities.interfaces import (
    ActivityEvents,
    ActivityLinkStore,
    ActivityStaffStore,
    ActivityStore,
    AnnouncementStore,
    CategoryStore,
    ScheduleStore,
    SlotStore,
)
from activities.service import ActivityService
from tests.unit.member_fakes import FakeAccess, FakeUsers
from tests.unit.org_fakes import FakeOrgs
from tests.unit.profile_fakes import FakeProfiles


class FakeActivities(ActivityStore):
    def __init__(self) -> None:
        self.rows: dict[UUID, Any] = {}

    def create(self, org_id, created_by, fields, now):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            id=uuid_utils.uuid7(), org_id=org_id, created_by=created_by,
            status="draft", published_at=None,
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
        return [r for r in self.rows.values() if r.org_id == org_id][:limit]

    def list_by_status(self, status, limit=50):  # noqa: ANN001, ANN202
        return [r for r in self.rows.values() if r.status == status][:limit]

    def list_by_category(self, category_id, limit=50):  # noqa: ANN001, ANN202
        return [
            r for r in self.rows.values() if r.category_id == category_id
        ][:limit]


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


class FakeLinks(ActivityLinkStore):
    def __init__(self) -> None:
        self.skills: dict[UUID, dict[UUID, bool]] = {}
        self.partners: dict[UUID, dict[UUID, tuple[str, str | None]]] = {}

    def set_skills(self, activity_id, edges):  # noqa: ANN001, ANN202
        self.skills[activity_id] = dict(edges)

    def list_skills(self, activity_id):  # noqa: ANN001, ANN202
        return [
            SimpleNamespace(
                activity_id=activity_id, skill_id=sid, is_required=req
            )
            for sid, req in self.skills.get(activity_id, {}).items()
        ]

    def set_partners(self, activity, edges):  # noqa: ANN001, ANN202
        self.partners[activity.id] = {
            oid: (role, note) for oid, role, note in edges
        }

    def list_partners(self, activity_id):  # noqa: ANN001, ANN202
        return [
            SimpleNamespace(org_id=oid, role=r, note=n)
            for oid, (r, n) in self.partners.get(activity_id, {}).items()
        ]

    def list_partner_feed(self, org_id, limit=50):  # noqa: ANN001, ANN202
        return []


class FakeStaff(ActivityStaffStore):
    def __init__(self) -> None:
        self.rows: dict[UUID, dict[UUID, str]] = {}

    def set_staff(self, activity_id, rows, assigned_by, now):  # noqa: ANN001, ANN202
        self.rows[activity_id] = dict(rows)

    def list_staff(self, activity_id):  # noqa: ANN001, ANN202
        return [
            SimpleNamespace(user_id=uid, staff_role=role, assigned_at=None)
            for uid, role in self.rows.get(activity_id, {}).items()
        ]


class FakeSchedules(ScheduleStore):
    def __init__(self) -> None:
        self.rows: dict[UUID, Any] = {}

    def create(self, schedule_id, activity_id, title, location, start_at, end_at, now):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            id=schedule_id, activity_id=activity_id, title=title,
            location=location, start_at=start_at, end_at=end_at,
            status="scheduled", created_at=now,
        )
        self.rows[schedule_id] = row
        return row

    def list(self, activity_id):  # noqa: ANN001, ANN202
        return [r for r in self.rows.values() if r.activity_id == activity_id]

    def delete(self, activity_id, schedule_id):  # noqa: ANN001, ANN202
        row = self.rows.get(schedule_id)
        if row is None or row.activity_id != activity_id:
            return False
        del self.rows[schedule_id]
        return True


class FakeSlots(SlotStore):
    """Resolves activity-wide listing through the schedules feed."""

    def __init__(self, schedules: FakeSchedules | None = None) -> None:
        self.rows: dict[UUID, Any] = {}
        self._schedules = schedules

    def list(self, schedule_id):  # noqa: ANN001, ANN202
        return [
            r for r in self.rows.values() if r.schedule_id == schedule_id
        ]

    def list_for_activity(self, activity_id):  # noqa: ANN001, ANN202
        schedule_ids = (
            {s.id for s in self._schedules.list(activity_id)}
            if self._schedules is not None
            else set(self.rows.keys())
        )
        return [
            r
            for r in self.rows.values()
            if r.schedule_id in schedule_ids
        ]

    def create(self, slot_id, schedule_id, title, capacity, start_at, end_at):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            slot_id=slot_id, schedule_id=schedule_id, title=title,
            capacity=capacity, registered=0, start_at=start_at,
            end_at=end_at,
        )
        self.rows[slot_id] = row
        return row

    def delete(self, schedule_id, slot_id):  # noqa: ANN001, ANN202
        row = self.rows.get(slot_id)
        if row is None or row.schedule_id != schedule_id:
            return False
        del self.rows[slot_id]
        return True


class FakeAnnouncements(AnnouncementStore):
    def __init__(self) -> None:
        self.rows: dict[UUID, list[Any]] = {}

    def create(self, activity_id, announcement_id, title, body, created_by, now):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            activity_id=activity_id, announcement_id=announcement_id,
            title=title, body=body, created_by=created_by,
            published_at=now,
        )
        self.rows.setdefault(activity_id, []).append(row)
        return row

    def list(self, activity_id, limit=50):  # noqa: ANN001, ANN202
        return self.rows.get(activity_id, [])[:limit]


class FakeActivityEvents(ActivityEvents):
    """Captures live activity events instead of publishing them."""

    def __init__(self) -> None:
        self.sent: list[tuple] = []

    def activity_changed(self, org_id, action, activity_id, actor_id, status):  # noqa: ANN001, ANN202
        self.sent.append((org_id, action, activity_id, actor_id, status))


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
