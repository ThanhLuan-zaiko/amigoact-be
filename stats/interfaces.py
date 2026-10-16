"""Ports for the stats context.

Stats is a read-only projection over existing feeds, so it reuses the
already-defined store interfaces (ActivityStore, MemberRepository,
HourLedgerStore, AttendanceStore, CertificateStore). The two stores
below own the materialized rollup tables.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from uuid import UUID

from stats.model import ActivityDailyStats, OrgMonthlyStats


class DailyStatsStore(ABC):
    """Persistence port for activity_daily_stats."""

    @abstractmethod
    def upsert(
        self,
        activity_id: UUID,
        day: date,
        registrations: int,
        attendees: int,
        hours_awarded: float,
    ) -> None:
        """Create-or-replace one day row."""

    @abstractmethod
    def list_days(
        self, activity_id: UUID, limit: int = 30
    ) -> list[ActivityDailyStats]:
        """Most recent days first."""


class MonthlyStatsStore(ABC):
    """Persistence port for org_monthly_stats."""

    @abstractmethod
    def upsert(
        self,
        org_id: UUID,
        month: str,
        activities: int,
        participants: int,
        hours: float,
        certificates: int,
    ) -> None:
        """Create-or-replace one month row."""

    @abstractmethod
    def list_months(
        self, org_id: UUID, limit: int = 12
    ) -> list[OrgMonthlyStats]:
        """Most recent months first."""
