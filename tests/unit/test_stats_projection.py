"""StatsProjectionService unit tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import uuid_utils

from stats.interfaces import DailyStatsStore, MonthlyStatsStore
from stats.projection_service import StatsProjectionService
from tests.unit.member_fakes import FakeAccess
from tests.unit.org_fakes import FakeOrgs
from tests.unit.registration_fakes import (
    FakeActivities,
    FakeAttendance,
    FakeRegistrations,
    published_activity,
)
from tests.unit.hour_fakes import FakeCertificates, FakeLedger


class FakeDaily(DailyStatsStore):
    def __init__(self) -> None:
        self.rows: dict = {}

    def upsert(self, activity_id, day, registrations, attendees, hours_awarded):
        self.rows[(activity_id, day)] = SimpleNamespace(
            activity_id=activity_id, day=day,
            registrations=registrations, attendees=attendees,
            hours_awarded=hours_awarded,
        )

    def list_days(self, activity_id, limit=30):
        return sorted(
            [r for r in self.rows.values() if r.activity_id == activity_id],
            key=lambda r: r.day, reverse=True,
        )[:limit]


class FakeMonthly(MonthlyStatsStore):
    def __init__(self) -> None:
        self.rows: dict = {}

    def upsert(self, org_id, month, activities, participants, hours, certificates):
        self.rows[(org_id, month)] = SimpleNamespace(
            org_id=org_id, month=month, activities=activities,
            participants=participants, hours=hours,
            certificates=certificates,
        )

    def list_months(self, org_id, limit=12):
        return sorted(
            [r for r in self.rows.values() if r.org_id == org_id],
            key=lambda r: r.month, reverse=True,
        )[:limit]


def _svc():
    orgs = FakeOrgs()
    activities = FakeActivities()
    regs = FakeRegistrations()
    attendance = FakeAttendance()
    hours = FakeLedger()
    certs = FakeCertificates()
    service = StatsProjectionService(
        orgs=orgs, activities=activities, registrations=regs,
        attendance=attendance, hours=hours, certificates=certs,
        daily=FakeDaily(), monthly=FakeMonthly(), access=FakeAccess(),
    )
    return service, orgs, activities, regs, attendance, hours, certs


def _org(orgs: FakeOrgs, owner: UUID):
    return orgs.create(
        uuid_utils.uuid7(), owner, "Club", "club", "", "club",
        "open", None, None, None, None, "none", datetime.now(UTC),
    )


def test_daily_rollup_materializes():
    service, orgs, activities, regs, attendance, hours, _ = _svc()
    owner = uuid_utils.uuid7()
    org = _org(orgs, owner)
    act = published_activity(activities, org.id, owner)
    student = uuid_utils.uuid7()
    yesterday = datetime.now(UTC) - timedelta(days=1)
    reg = regs.create(act.id, student, None, uuid_utils.uuid7(), yesterday)
    reg.registered_at = yesterday
    attendance.create(
        reg.registration_id, act.id, student, uuid_utils.uuid7(),
        "qr", owner, yesterday,
    )
    entry = hours.record(
        uuid_utils.uuid7(), org.id, student, act.id, "manual",
        2.5, "2026A", None, owner, None, datetime.now(UTC),
    )
    hours.set_status(entry, org.id, "approved", owner, yesterday)

    rows = service.activity_daily(act.id, owner)
    assert len(rows) == 1
    assert rows[0].registrations == 1
    assert rows[0].attendees == 1
    assert rows[0].hours_awarded == 2.5


def test_monthly_rollup_counts_certs():
    service, orgs, activities, _, _, _, certs = _svc()
    owner = uuid_utils.uuid7()
    org = _org(orgs, owner)
    act = published_activity(activities, org.id, owner)
    certs.issue(
        uuid_utils.uuid7(), act.id, uuid_utils.uuid7(), None,
        "C-1", owner, datetime.now(UTC),
    )
    rows = service.org_monthly(org.id, owner)
    assert len(rows) == 1
    assert rows[0].activities == 1
    assert rows[0].certificates == 1
