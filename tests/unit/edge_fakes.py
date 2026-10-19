"""In-memory edge-table ports for activity unit tests.

Split out of activity_fakes.py for the 350-line rule: these fakes back
the detail aggregate (skills, partners, staff, schedules, slots,
announcements) rather than the activity lifecycle itself.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from activities.edge_interfaces import (
    ActivityLinkStore,
    ActivityStaffStore,
    AnnouncementStore,
    ScheduleStore,
    SlotStore,
)


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
