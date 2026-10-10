"""Shared in-memory ports for HourService / CertificateService tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import uuid_utils

from certificates.interfaces import CertificateStore
from certificates.service import CertificateService
from hours.interfaces import HourLedgerStore
from hours.service import HourService
from tests.unit.activity_fakes import FakeActivities
from tests.unit.member_fakes import FakeAccess, FakeUsers
from tests.unit.org_fakes import FakeOrgs
from tests.unit.registration_fakes import FakeNotifications, FakeRegistrations


class FakeLedger(HourLedgerStore):
    def __init__(self) -> None:
        self.rows: dict[UUID, Any] = {}
        self.queue: dict[tuple[UUID, UUID], Any] = {}
        self.summaries: dict[tuple[UUID, str], Any] = {}

    def record(self, entry_id, org_id, student_id, activity_id, source, hours, term, registration_id, recorded_by, note, now):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            entry_id=entry_id, student_id=student_id,
            activity_id=activity_id, source=source, hours=hours,
            term=term, registration_id=registration_id,
            status="pending", approved_by=None, approved_at=None,
            recorded_at=now, recorded_by=recorded_by, note=note,
        )
        self.rows[entry_id] = row
        self.queue[(org_id, entry_id)] = row
        return row

    def get(self, entry_id):  # noqa: ANN001, ANN202
        return self.rows.get(entry_id)

    def set_status(self, entry, org_id, status, reviewer_id, now):  # noqa: ANN001, ANN202
        row = self.rows[entry.entry_id]
        row.status = status
        row.approved_by = reviewer_id
        row.approved_at = now
        self.queue.pop((org_id, entry.entry_id), None)
        if status == "approved":
            key = (entry.student_id, entry.term)
            cur = self.summaries.get(
                key, SimpleNamespace(total_hours=0.0, activities_count=0)
            )
            self.summaries[key] = SimpleNamespace(
                term=entry.term,
                total_hours=cur.total_hours + entry.hours,
                activities_count=cur.activities_count + 1,
            )
        return row

    def list_pending(self, org_id, limit=100):  # noqa: ANN001, ANN202
        return [
            r for (oid, _), r in self.queue.items() if oid == org_id
        ][:limit]

    def list_by_student(self, student_id, limit=100):  # noqa: ANN001, ANN202
        return [
            r for r in self.rows.values() if r.student_id == student_id
        ][:limit]

    def list_by_activity(self, activity_id, limit=100):  # noqa: ANN001, ANN202
        return [
            r for r in self.rows.values() if r.activity_id == activity_id
        ][:limit]

    def summary_for_student(self, student_id):  # noqa: ANN001, ANN202
        return [
            r for (sid, _), r in self.summaries.items() if sid == student_id
        ]


class FakeCertificates(CertificateStore):
    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, UUID], Any] = {}
        self.serials: dict[str, Any] = {}

    def issue(self, certificate_id, activity_id, student_id, registration_id, serial_no, issued_by, now):  # noqa: ANN001, ANN202
        from core.exceptions import CertificateExistsError

        if serial_no in self.serials:
            raise CertificateExistsError("serial taken")
        row = SimpleNamespace(
            certificate_id=certificate_id, activity_id=activity_id,
            student_id=student_id, registration_id=registration_id,
            serial_no=serial_no, issued_at=now, issued_by=issued_by,
            status="issued", template_id=None, file_media_id=None,
        )
        self.rows[(activity_id, student_id)] = row
        self.serials[serial_no] = row
        return row

    def get(self, activity_id, student_id):  # noqa: ANN001, ANN202
        return self.rows.get((activity_id, student_id))

    def get_by_serial(self, serial_no):  # noqa: ANN001, ANN202
        row = self.serials.get(serial_no)
        if row is None:
            return None
        return SimpleNamespace(
            serial_no=serial_no,
            certificate_id=row.certificate_id,
            activity_id=row.activity_id,
            student_id=row.student_id,
            status=row.status,
        )

    def revoke(self, certificate, reason, revoked_by, now):  # noqa: ANN001, ANN202
        certificate.status = "revoked"
        return certificate

    def list_by_student(self, student_id, limit=50):  # noqa: ANN001, ANN202
        return [
            r for r in self.rows.values() if r.student_id == student_id
        ][:limit]

    def list_by_activity(self, activity_id, limit=500):  # noqa: ANN001, ANN202
        return [
            r for r in self.rows.values() if r.activity_id == activity_id
        ][:limit]


class FakeLeaderboard:
    """In-memory LeaderboardStore: rows keyed (term, student_id)."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, UUID], Any] = {}
        self.calls: list[tuple] = []

    def put(self, term, student_id, student_name, previous_total, new_total, now):  # noqa: ANN001, ANN202
        self.calls.append((term, student_id, previous_total, new_total))
        self.rows.pop((term, student_id), None)
        self.rows[(term, student_id)] = SimpleNamespace(
            term=term, student_id=student_id,
            student_name=student_name, total_hours=new_total,
            updated_at=now,
        )

    def top(self, term, limit=50):  # noqa: ANN001, ANN202
        rows = [r for (t, _), r in self.rows.items() if t == term]
        rows.sort(key=lambda r: (-r.total_hours, str(r.student_id)))
        return rows[:limit]

    def terms(self):  # noqa: ANN001, ANN202
        return sorted({t for (t, _) in self.rows})


def make_hour_service(
    leaderboard=None, users=None,
) -> tuple[
    HourService, FakeLedger, FakeActivities, FakeOrgs, FakeAccess,
    FakeNotifications,
]:
    ledger = FakeLedger()
    activities = FakeActivities()
    orgs = FakeOrgs()
    access = FakeAccess()
    notes = FakeNotifications()
    service = HourService(
        ledger=ledger, activities=activities, orgs=orgs,
        access=access, notifications=notes,
        leaderboard=leaderboard, users=users,
    )
    return service, ledger, activities, orgs, access, notes


def make_cert_service() -> tuple[
    CertificateService, FakeCertificates, FakeRegistrations,
    FakeActivities, FakeOrgs, FakeAccess, FakeUsers, FakeNotifications,
]:
    certs = FakeCertificates()
    regs = FakeRegistrations()
    activities = FakeActivities()
    orgs = FakeOrgs()
    access = FakeAccess()
    users = FakeUsers()
    notes = FakeNotifications()
    service = CertificateService(
        certificates=certs, registrations=regs, activities=activities,
        orgs=orgs, users=users, access=access, notifications=notes,
    )
    return service, certs, regs, activities, orgs, access, users, notes


def uid() -> UUID:
    return uuid_utils.uuid7()
