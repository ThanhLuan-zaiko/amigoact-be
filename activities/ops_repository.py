"""cqlengine persistence for schedules and announcements."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from activities.interfaces import AnnouncementStore, ScheduleStore
from activities.model import (
    ActivityAnnouncement,
    ActivitySchedule,
    ScheduleByActivity,
)


class CqlScheduleStore(ScheduleStore):
    """Schedules are per-activity sessions created by managers."""

    def create(
        self,
        schedule_id: UUID,
        activity_id: UUID,
        title: str,
        location: str | None,
        start_at: datetime | None,
        end_at: datetime | None,
        now: datetime,
    ) -> ActivitySchedule:
        row = ActivitySchedule.create(
            id=schedule_id,
            activity_id=activity_id,
            title=title,
            location=location,
            start_at=start_at,
            end_at=end_at,
            status="scheduled",
            created_at=now,
        )
        if start_at is not None:
            ScheduleByActivity.create(
                activity_id=activity_id,
                start_at=start_at,
                schedule_id=schedule_id,
                title=title,
                status="scheduled",
            )
        return row

    def list(self, activity_id: UUID) -> list[ActivitySchedule]:
        feed = list(
            ScheduleByActivity.objects(activity_id=activity_id).all()
        )
        rows = {
            row.id: row
            for row in (
                ActivitySchedule.objects(id=f.schedule_id).first()
                for f in feed
            )
            if row is not None
        }
        return [rows[f.schedule_id] for f in feed if f.schedule_id in rows]

    def delete(self, activity_id: UUID, schedule_id: UUID) -> bool:
        row = ActivitySchedule.objects(id=schedule_id).first()
        if row is None or row.activity_id != activity_id:
            return False
        if row.start_at is not None:
            ScheduleByActivity.objects(
                activity_id=activity_id,
                start_at=row.start_at,
                schedule_id=schedule_id,
            ).delete()
        ActivitySchedule.objects(id=schedule_id).delete()
        return True


class CqlAnnouncementStore(AnnouncementStore):
    """News board appended by managers, newest first."""

    def create(
        self,
        activity_id: UUID,
        announcement_id: UUID,
        title: str,
        body: str,
        created_by: UUID,
        now: datetime,
    ) -> ActivityAnnouncement:
        return ActivityAnnouncement.create(
            activity_id=activity_id,
            published_at=now,
            announcement_id=announcement_id,
            title=title,
            body=body,
            created_by=created_by,
        )

    def list(
        self, activity_id: UUID, limit: int = 50
    ) -> list[ActivityAnnouncement]:
        return list(
            ActivityAnnouncement.objects(activity_id=activity_id)
            .limit(limit)
            .all()
        )
