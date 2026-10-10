"""Unit tests for HourService queue/rollup and CertificateService."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
import uuid_utils

from core.exceptions import (
    CertificateExistsError,
    ForbiddenError,
    InvalidHoursStateError,
    InvalidRegistrationStateError,
    NotFoundError,
)
from hours.service import term_of
from tests.unit.activity_fakes import _fields, _org_with_owner
from tests.unit.hour_fakes import (
    make_cert_service,
    make_hour_service,
    uid,
)


def test_term_of() -> None:
    assert term_of(datetime(2026, 2, 1, tzinfo=UTC)) == "2026-H1"
    assert term_of(datetime(2026, 8, 1, tzinfo=UTC)) == "2026-H2"


def _setup() -> tuple:
    service, ledger, activities, orgs, access, notes = make_hour_service()
    owner = uid()
    org = _org_with_owner(orgs, owner)
    activity = activities.create(
        org.id, owner, _fields(None), datetime.now(UTC)
    )
    return service, ledger, activity, org, owner, access, notes


def test_record_attendance_queues_pending() -> None:
    service, ledger, activity, org, owner, _acc, _n = _setup()
    student = uid()
    service.record_attendance(
        org.id, activity.id, student, uid(), 3.5, owner
    )
    pending = ledger.list_pending(org.id)
    assert len(pending) == 1
    assert pending[0].status == "pending"
    assert pending[0].source == "attendance"


def test_submit_manual_requires_manager() -> None:
    service, _l, activity, org, owner, access, _n = _setup()
    entry = service.submit_manual(
        org.id, activity.id, uid(), 2.0, "helped", owner
    )
    assert entry.source == "manual"
    with pytest.raises(ForbiddenError):
        service.submit_manual(
            org.id, activity.id, uid(), 2.0, None, uid()
        )
    assert access.audit[-1][2] == "denied"


def test_manual_hours_must_be_positive() -> None:
    service, _l, activity, org, owner, _acc, _n = _setup()
    with pytest.raises(InvalidHoursStateError):
        service.submit_manual(
            org.id, activity.id, uid(), 0.0, None, owner
        )


def test_approve_rolls_up_summary_and_notifies() -> None:
    service, ledger, activity, org, owner, _acc, notes = _setup()
    student = uid()
    service.record_attendance(
        org.id, activity.id, student, uid(), 4.0, owner
    )
    entry = next(iter(ledger.rows.values()))
    updated = service.review(entry.entry_id, owner, "approved", None)
    assert updated.status == "approved"
    assert ledger.list_pending(org.id) == []
    summary = service.my_summary(student)[0]
    assert summary.total_hours == 4.0
    assert summary.activities_count == 1
    assert notes.sent and notes.sent[-1][0] == student


def test_reject_removes_from_queue() -> None:
    service, ledger, activity, org, owner, _acc, _n = _setup()
    student = uid()
    service.record_attendance(
        org.id, activity.id, student, uid(), 4.0, owner
    )
    entry = next(iter(ledger.rows.values()))
    service.review(entry.entry_id, owner, "rejected", "duplicate")
    assert entry.status == "rejected"
    assert ledger.list_pending(org.id) == []
    assert service.my_summary(student) == []


def test_double_review_rejected() -> None:
    service, ledger, activity, org, owner, _acc, _n = _setup()
    service.record_attendance(
        org.id, activity.id, uid(), uid(), 4.0, owner
    )
    entry = next(iter(ledger.rows.values()))
    service.review(entry.entry_id, owner, "approved", None)
    with pytest.raises(InvalidHoursStateError):
        service.review(entry.entry_id, owner, "rejected", None)


def test_review_requires_manager() -> None:
    service, ledger, activity, org, owner, _acc, _n = _setup()
    service.record_attendance(
        org.id, activity.id, uid(), uid(), 4.0, owner
    )
    entry = next(iter(ledger.rows.values()))
    with pytest.raises(ForbiddenError):
        service.review(entry.entry_id, uid(), "approved", None)


def _cert_setup() -> tuple:
    svc, certs, regs, activities, orgs, access, users, notes = (
        make_cert_service()
    )
    owner = uid()
    org = _org_with_owner(orgs, owner)
    activity = activities.create(
        org.id, owner, _fields(None), datetime.now(UTC)
    )
    return svc, certs, regs, activity, org, owner, users, notes


def test_issue_requires_attended() -> None:
    svc, _c, regs, activity, _o, owner, _u, _n = _cert_setup()
    student = uid()
    with pytest.raises(InvalidRegistrationStateError):
        svc.issue(activity.id, student, owner)
    regs.guards[(activity.id, student, UUID(int=0))] = type(
        "G", (), {"status": "approved", "registration_id": uid()}
    )()
    with pytest.raises(InvalidRegistrationStateError):
        svc.issue(activity.id, student, owner)


def test_issue_then_verify_serial() -> None:
    svc, certs, regs, activity, _o, owner, users, notes = _cert_setup()
    student = uid()
    users.add(student, "s@example.com", "Sinh viên")
    reg = regs.create(
        activity.id, student, None, uuid_utils.uuid7(), datetime.now(UTC)
    )
    reg.status = "attended"
    cert = svc.issue(activity.id, student, owner)
    assert cert.serial_no.startswith("AMG-")
    assert notes.sent and notes.sent[-1][0] == student
    result = svc.verify(cert.serial_no)
    assert result.status == "issued"
    assert result.student_name == "Sinh viên"


def test_issue_twice_conflict() -> None:
    svc, _c, regs, activity, _o, owner, _u, _n = _cert_setup()
    student = uid()
    reg = regs.create(
        activity.id, student, None, uuid_utils.uuid7(), datetime.now(UTC)
    )
    reg.status = "attended"
    svc.issue(activity.id, student, owner)
    with pytest.raises(CertificateExistsError):
        svc.issue(activity.id, student, owner)


def test_revoke_flips_status_and_verify_shows_it() -> None:
    svc, _c, regs, activity, _o, owner, _u, _n = _cert_setup()
    student = uid()
    reg = regs.create(
        activity.id, student, None, uuid_utils.uuid7(), datetime.now(UTC)
    )
    reg.status = "attended"
    cert = svc.issue(activity.id, student, owner)
    out = svc.revoke(activity.id, student, owner, "error")
    assert out.status == "revoked"
    assert svc.verify(cert.serial_no).status == "revoked"


def test_issue_requires_manager() -> None:
    svc, _c, regs, activity, _o, owner, _u, _n = _cert_setup()
    student = uid()
    reg = regs.create(
        activity.id, student, None, uuid_utils.uuid7(), datetime.now(UTC)
    )
    reg.status = "attended"
    with pytest.raises(ForbiddenError):
        svc.issue(activity.id, student, uid())


def test_verify_unknown_serial_404() -> None:
    svc, *_ = _cert_setup()
    with pytest.raises(NotFoundError):
        svc.verify("AMG-2026-NOPE")
