"""cqlengine persistence for sessions, QR codes, and scan logs."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from registrations.session_interfaces import (
    AppealStore,
    QrStore,
    ScanLogStore,
    SessionStore,
    SummaryStore,
)
from registrations.model import (
    AttendanceAppeal,
    AttendanceSession,
    AttendanceSummary,
    QrCode,
    QrScanLog,
)


class CqlSessionStore(SessionStore):
    """Sessions clustered under their schedule partition."""

    def create(
        self,
        session_id: UUID,
        schedule_id: UUID,
        title: str,
        qr_code: str,
        opens_at: datetime | None,
        closes_at: datetime | None,
        status: str,
        created_by: UUID,
    ) -> AttendanceSession:
        return AttendanceSession.create(
            session_id=session_id,
            schedule_id=schedule_id,
            title=title,
            qr_code=qr_code,
            opens_at=opens_at,
            closes_at=closes_at,
            status=status,
            created_by=created_by,
        )

    def list(self, schedule_id: UUID) -> list[AttendanceSession]:
        return list(
            AttendanceSession.objects(schedule_id=schedule_id).all()
        )

    def get(
        self, schedule_id: UUID, session_id: UUID
    ) -> AttendanceSession | None:
        return AttendanceSession.objects(
            schedule_id=schedule_id, session_id=session_id
        ).first()

    def set_status(
        self, schedule_id: UUID, session_id: UUID, status: str
    ) -> bool:
        if self.get(schedule_id, session_id) is None:
            return False
        AttendanceSession.objects(
            schedule_id=schedule_id, session_id=session_id
        ).update(status=status)
        return True


class CqlQrStore(QrStore):
    """Codes keyed by their string; used_count via read-then-write."""

    def create(
        self,
        code: str,
        session_id: UUID,
        schedule_id: UUID,
        activity_id: UUID,
        expires_at: datetime | None,
        max_uses: int | None,
    ) -> QrCode:
        return QrCode.create(
            code=code,
            session_id=session_id,
            schedule_id=schedule_id,
            activity_id=activity_id,
            expires_at=expires_at,
            max_uses=max_uses,
            used_count=0,
            status="active",
        )

    def get(self, code: str) -> QrCode | None:
        return QrCode.objects(code=code).first()

    def set_status(self, code: str, status: str) -> None:
        QrCode.objects(code=code).update(status=status)

    def bump_used(self, code: str) -> None:
        row = self.get(code)
        if row is not None:
            QrCode.objects(code=code).update(
                used_count=(row.used_count or 0) + 1
            )


class CqlScanLogStore(ScanLogStore):
    """Append-only audit feed partitioned by code."""

    def log(
        self,
        qr_code: str,
        log_id: UUID,
        student_id: UUID,
        result: str,
        device_info: str | None,
        now: datetime,
    ) -> QrScanLog:
        return QrScanLog.create(
            qr_code=qr_code,
            scanned_at=now,
            log_id=log_id,
            student_id=student_id,
            result=result,
            device_info=device_info,
        )

    def list(self, qr_code: str, limit: int = 200) -> list[QrScanLog]:
        return list(
            QrScanLog.objects(qr_code=qr_code).limit(limit)
        )


class CqlAppealStore(AppealStore):
    """Appeals cluster inside one activity partition."""

    def create(
        self,
        activity_id: UUID,
        student_id: UUID,
        appeal_id: UUID,
        record_id: UUID | None,
        reason: str,
        now: datetime,
    ) -> AttendanceAppeal:
        return AttendanceAppeal.create(
            activity_id=activity_id,
            student_id=student_id,
            appeal_id=appeal_id,
            record_id=record_id,
            reason=reason,
            status="pending",
            created_at=now,
        )

    def list_by_activity(
        self, activity_id: UUID, limit: int = 200
    ) -> list[AttendanceAppeal]:
        return list(
            AttendanceAppeal.objects(
                activity_id=activity_id
            ).limit(limit)
        )

    def list_for_student(
        self, activity_id: UUID, student_id: UUID
    ) -> list[AttendanceAppeal]:
        return list(
            AttendanceAppeal.objects(
                activity_id=activity_id, student_id=student_id
            ).all()
        )

    def get(
        self, activity_id: UUID, student_id: UUID, appeal_id: UUID
    ) -> AttendanceAppeal | None:
        return AttendanceAppeal.objects(
            activity_id=activity_id,
            student_id=student_id,
            appeal_id=appeal_id,
        ).first()

    def resolve(
        self,
        activity_id: UUID,
        student_id: UUID,
        appeal_id: UUID,
        status: str,
        resolved_by: UUID,
        now: datetime,
    ) -> AttendanceAppeal | None:
        if self.get(activity_id, student_id, appeal_id) is None:
            return None
        AttendanceAppeal.objects(
            activity_id=activity_id,
            student_id=student_id,
            appeal_id=appeal_id,
        ).update(
            status=status, resolved_by=resolved_by, resolved_at=now
        )
        return self.get(activity_id, student_id, appeal_id)


class CqlSummaryStore(SummaryStore):
    """Single-row rollup keyed by registration."""

    def get(self, registration_id: UUID) -> AttendanceSummary | None:
        return AttendanceSummary.objects(
            registration_id=registration_id
        ).first()

    def upsert(
        self,
        registration_id: UUID,
        activity_id: UUID,
        student_id: UUID,
        sessions_total: int,
        sessions_attended: int,
        minutes_attended: int,
        status: str,
        now: datetime,
    ) -> AttendanceSummary:
        return AttendanceSummary.create(
            registration_id=registration_id,
            activity_id=activity_id,
            student_id=student_id,
            sessions_total=sessions_total,
            sessions_attended=sessions_attended,
            minutes_attended=minutes_attended,
            status=status,
            updated_at=now,
        )
