"""Materializes activity_daily_stats + org_monthly_stats on read.

Rollups are recomputed partition-locally from the live feeds and
upserted, so the tables stay warm without touching write paths.
"""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from activities.interfaces import ActivityStore
from certificates.interfaces import CertificateStore
from core.exceptions import ForbiddenError, NotFoundError
from hours.interfaces import HourLedgerStore
from orgs.interfaces import OrgRepository
from rbac.interfaces import AccessControl
from registrations.interfaces import (
    AttendanceStore,
    RegistrationStore,
)
from stats.interfaces import DailyStatsStore, MonthlyStatsStore
from stats.model import ActivityDailyStats, OrgMonthlyStats

_MAX_ACTIVITIES = 50


def _day_of(value) -> object | None:
    return getattr(value, "date", lambda: None)() if value else None


def _month_of(value) -> str | None:
    day = _day_of(value)
    return day.strftime("%Y-%m") if day else None


class StatsProjectionService:
    """Manager-scoped materialized rollups over the live feeds."""

    def __init__(
        self,
        orgs: OrgRepository,
        activities: ActivityStore,
        registrations: RegistrationStore,
        attendance: AttendanceStore,
        hours: HourLedgerStore,
        certificates: CertificateStore,
        daily: DailyStatsStore,
        monthly: MonthlyStatsStore,
        access: AccessControl,
    ) -> None:
        self._orgs = orgs
        self._activities = activities
        self._registrations = registrations
        self._attendance = attendance
        self._hours = hours
        self._certificates = certificates
        self._daily = daily
        self._monthly = monthly
        self._access = access

    def _require_manager(self, org_id: UUID, actor_id: UUID) -> None:
        org = self._orgs.get_by_id(org_id)
        if org is None or getattr(org, "deleted_at", None) is not None:
            raise NotFoundError("Organization not found.")
        if org.owner_id != actor_id and not self._access.has_permission(
            org_id, actor_id, "activity:manage"
        ):
            raise ForbiddenError("Only org managers can view stats.")

    def _org_of_activity(self, activity_id: UUID, actor_id: UUID) -> UUID:
        row = self._activities.get(activity_id)
        if row is None:
            raise NotFoundError("Activity not found.")
        self._require_manager(row.org_id, actor_id)
        return row.org_id

    def activity_daily(
        self, activity_id: UUID, actor_id: UUID, limit: int = 90
    ) -> list[ActivityDailyStats]:
        """Recompute per-day buckets, upsert them, return newest days."""
        self._org_of_activity(activity_id, actor_id)
        buckets: dict = defaultdict(lambda: [0, 0, 0.0])
        for row in self._registrations.list_by_activity(activity_id):
            day = _day_of(getattr(row, "registered_at", None))
            if day is not None:
                buckets[day][0] += 1
        for row in self._attendance.list_by_activity(activity_id):
            day = _day_of(getattr(row, "scanned_at", None))
            if day is not None:
                buckets[day][1] += 1
        for entry in self._hours.list_by_activity(activity_id):
            if entry.status != "approved":
                continue
            day = _day_of(getattr(entry, "approved_at", None))
            if day is not None:
                buckets[day][2] += entry.hours or 0.0
        for day, (regs, attended, hrs) in buckets.items():
            self._daily.upsert(
                activity_id, day, regs, attended, round(hrs, 1)
            )
        return self._daily.list_days(activity_id, limit)

    def org_monthly(
        self, org_id: UUID, actor_id: UUID, limit: int = 12
    ) -> list[OrgMonthlyStats]:
        """Recompute per-month buckets across the org, upsert, return."""
        self._require_manager(org_id, actor_id)
        buckets: dict = defaultdict(lambda: [0, 0, 0.0, 0])
        for activity in self._activities.list_by_org(
            org_id, _MAX_ACTIVITIES
        ):
            month = _month_of(
                getattr(activity, "published_at", None)
                or getattr(activity, "created_at", None)
            )
            if month is not None:
                buckets[month][0] += 1
            for row in self._registrations.list_by_activity(activity.id):
                m = _month_of(getattr(row, "registered_at", None))
                if m is not None:
                    buckets[m][1] += 1
            for entry in self._hours.list_by_activity(activity.id):
                if entry.status != "approved":
                    continue
                m = _month_of(getattr(entry, "approved_at", None))
                if m is not None:
                    buckets[m][2] += entry.hours or 0.0
            for row in self._certificates.list_by_activity(activity.id):
                if getattr(row, "status", None) != "issued":
                    continue
                m = _month_of(getattr(row, "issued_at", None))
                if m is not None:
                    buckets[m][3] += 1
        for month, (acts, parts, hrs, certs) in buckets.items():
            self._monthly.upsert(
                org_id, month, acts, parts, round(hrs, 1), certs
            )
        return self._monthly.list_months(org_id, limit)
