"""In-memory fakes for session/QR/scan-log stores."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import uuid_utils

from registrations.session_interfaces import (
    AppealStore,
    QrStore,
    ScanLogStore,
    SessionStore,
    SummaryStore,
)


class FakeSessions(SessionStore):
    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, UUID], Any] = {}

    def create(self, session_id, schedule_id, title, qr_code, opens_at, closes_at, status, created_by):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            session_id=session_id, schedule_id=schedule_id, title=title,
            qr_code=qr_code, opens_at=opens_at, closes_at=closes_at,
            status=status, created_by=created_by,
        )
        self.rows[(schedule_id, session_id)] = row
        return row

    def list(self, schedule_id):  # noqa: ANN001, ANN202
        return [
            r for (sid, _), r in self.rows.items() if sid == schedule_id
        ]

    def get(self, schedule_id, session_id):  # noqa: ANN001, ANN202
        return self.rows.get((schedule_id, session_id))

    def set_status(self, schedule_id, session_id, status):  # noqa: ANN001, ANN202
        row = self.rows.get((schedule_id, session_id))
        if row is None:
            return False
        row.status = status
        return True


class FakeQrs(QrStore):
    def __init__(self) -> None:
        self.rows: dict[str, Any] = {}

    def create(self, code, session_id, schedule_id, activity_id, expires_at, max_uses):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            code=code, session_id=session_id, schedule_id=schedule_id,
            activity_id=activity_id, expires_at=expires_at,
            max_uses=max_uses, used_count=0, status="active",
        )
        self.rows[code] = row
        return row

    def get(self, code):  # noqa: ANN001, ANN202
        return self.rows.get(code)

    def set_status(self, code, status):  # noqa: ANN001, ANN202
        if code in self.rows:
            self.rows[code].status = status

    def bump_used(self, code):  # noqa: ANN001, ANN202
        if code in self.rows:
            self.rows[code].used_count += 1


class FakeScanLogs(ScanLogStore):
    def __init__(self) -> None:
        self.rows: list[Any] = []

    def log(self, qr_code, log_id, student_id, result, device_info, now):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            qr_code=qr_code, scanned_at=now, log_id=log_id,
            student_id=student_id, result=result, device_info=device_info,
        )
        self.rows.append(row)
        return row

    def list(self, qr_code, limit=200):  # noqa: ANN001, ANN202
        return [
            r for r in reversed(self.rows) if r.qr_code == qr_code
        ][:limit]


class FakeAppeals(AppealStore):
    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, UUID, UUID], Any] = {}

    def create(self, activity_id, student_id, appeal_id, record_id, reason, now):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            activity_id=activity_id, student_id=student_id,
            appeal_id=appeal_id, record_id=record_id, reason=reason,
            status="pending", resolved_by=None, resolved_at=None,
            created_at=now,
        )
        self.rows[(activity_id, student_id, appeal_id)] = row
        return row

    def list_by_activity(self, activity_id, limit=200):  # noqa: ANN001, ANN202
        return [
            r for (aid, _, _), r in self.rows.items()
            if aid == activity_id
        ][:limit]

    def list_for_student(self, activity_id, student_id):  # noqa: ANN001, ANN202
        return [
            r for (aid, sid, _), r in self.rows.items()
            if aid == activity_id and sid == student_id
        ]

    def get(self, activity_id, student_id, appeal_id):  # noqa: ANN001, ANN202
        return self.rows.get((activity_id, student_id, appeal_id))

    def resolve(self, activity_id, student_id, appeal_id, status, resolved_by, now):  # noqa: ANN001, ANN202
        row = self.get(activity_id, student_id, appeal_id)
        if row is None:
            return None
        row.status = status
        row.resolved_by = resolved_by
        row.resolved_at = now
        return row


class FakeSummaries(SummaryStore):
    def __init__(self) -> None:
        self.rows: dict[UUID, Any] = {}

    def get(self, registration_id):  # noqa: ANN001, ANN202
        return self.rows.get(registration_id)

    def upsert(self, registration_id, activity_id, student_id, sessions_total, sessions_attended, minutes_attended, status, now):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            registration_id=registration_id, activity_id=activity_id,
            student_id=student_id, sessions_total=sessions_total,
            sessions_attended=sessions_attended,
            minutes_attended=minutes_attended, status=status,
            updated_at=now,
        )
        self.rows[registration_id] = row
        return row
