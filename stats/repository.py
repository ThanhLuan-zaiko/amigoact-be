"""cqlengine persistence for the materialized stats tables."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from stats.interfaces import DailyStatsStore, MonthlyStatsStore
from stats.model import ActivityDailyStats, OrgMonthlyStats


class CqlDailyStatsStore(DailyStatsStore):
    def upsert(
        self,
        activity_id: UUID,
        day: date,
        registrations: int,
        attendees: int,
        hours_awarded: float,
    ) -> None:
        ActivityDailyStats.objects(
            activity_id=activity_id, day=day
        ).update(
            registrations=registrations,
            attendees=attendees,
            hours_awarded=hours_awarded,
        )

    def list_days(
        self, activity_id: UUID, limit: int = 30
    ) -> list[ActivityDailyStats]:
        return list(
            ActivityDailyStats.objects(activity_id=activity_id).limit(
                limit
            )
        )


class CqlMonthlyStatsStore(MonthlyStatsStore):
    def upsert(
        self,
        org_id: UUID,
        month: str,
        activities: int,
        participants: int,
        hours: float,
        certificates: int,
    ) -> None:
        OrgMonthlyStats.objects(org_id=org_id, month=month).update(
            activities=activities,
            participants=participants,
            hours=hours,
            certificates=certificates,
        )

    def list_months(
        self, org_id: UUID, limit: int = 12
    ) -> list[OrgMonthlyStats]:
        return list(
            OrgMonthlyStats.objects(org_id=org_id).limit(limit)
        )
