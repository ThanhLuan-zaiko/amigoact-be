"""QR-session attendance: managers mint sessions, students scan codes."""

from __future__ import annotations

import secrets
from uuid import UUID

from activities.interfaces import ScheduleStore
from core.exceptions import (
    AlreadyCheckedInError,
    InvalidRegistrationStateError,
    NotFoundError,
)
from core.ids import uuid7
from core.security import utcnow
from registrations.session_interfaces import (
    QrStore,
    ScanLogStore,
    SessionStore,
    SummaryStore,
)
from registrations.model import (
    AttendanceSession,
    AttendanceSummary,
    QrScanLog,
)
from registrations.service import _RegistrationBase

SESSION_TRANSITIONS = {"scheduled": {"open"}, "open": {"closed"}}


class SessionService(_RegistrationBase):
    """Sessions bound to schedules; scans validate code + registration."""

    def __init__(
        self,
        *args,
        sessions: SessionStore,
        qrcodes: QrStore,
        scanlogs: ScanLogStore,
        schedules: ScheduleStore,
        summaries: SummaryStore | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._sessions = sessions
        self._qrcodes = qrcodes
        self._scanlogs = scanlogs
        self._schedules = schedules
        self._summaries = summaries

    def _session(self, schedule_id: UUID, session_id: UUID):
        row = self._sessions.get(schedule_id, session_id)
        if row is None:
            raise NotFoundError("Session not found.")
        return row

    def _schedule(self, activity_id: UUID, schedule_id: UUID):
        schedule = next(
            (
                s
                for s in self._schedules.list(activity_id)
                if s.id == schedule_id
            ),
            None,
        )
        if schedule is None:
            raise NotFoundError("Schedule not found.")
        return schedule

    def create_session(
        self,
        activity_id: UUID,
        schedule_id: UUID,
        actor_id: UUID,
        title: str,
        opens_at=None,
        closes_at=None,
        max_uses: int | None = None,
    ) -> AttendanceSession:
        """Manager mints a session plus its active QR code."""
        activity = self._activity(activity_id)
        self._require_manager(
            activity.org_id, actor_id, "attendance.session"
        )
        self._schedule(activity_id, schedule_id)
        code = secrets.token_urlsafe(9)
        session = self._sessions.create(
            uuid7(), schedule_id, title.strip(), code,
            opens_at, closes_at, "scheduled", actor_id,
        )
        self._qrcodes.create(
            code, session.session_id, schedule_id, activity_id,
            closes_at, max_uses,
        )
        return session

    def list_sessions(
        self, activity_id: UUID, viewer_id: UUID
    ) -> list[AttendanceSession]:
        """Manager feed: every session across the activity's schedules."""
        activity = self._activity(activity_id)
        self._require_manager(
            activity.org_id, viewer_id, "attendance.session"
        )
        rows: list[AttendanceSession] = []
        for schedule in self._schedules.list(activity_id):
            rows.extend(self._sessions.list(schedule.id))
        return rows

    def set_status(
        self,
        activity_id: UUID,
        schedule_id: UUID,
        session_id: UUID,
        actor_id: UUID,
        target: str,
    ) -> AttendanceSession:
        """scheduled -> open -> closed; closing disables the code."""
        activity = self._activity(activity_id)
        self._require_manager(
            activity.org_id, actor_id, "attendance.session"
        )
        session = self._session(schedule_id, session_id)
        if target not in SESSION_TRANSITIONS.get(session.status, set()):
            raise InvalidRegistrationStateError(
                f"Cannot move session from {session.status} to {target}."
            )
        if not self._sessions.set_status(schedule_id, session_id, target):
            raise NotFoundError("Session not found.")
        if target == "closed":
            self._qrcodes.set_status(session.qr_code, "disabled")
        return self._session(schedule_id, session_id)

    def _log(
        self,
        code: str,
        student_id: UUID,
        result: str,
        device_info: str | None,
    ) -> None:
        self._scanlogs.log(
            code, uuid7(), student_id, result, device_info, utcnow()
        )

    def scan(
        self, code: str, student_id: UUID, device_info: str | None = None
    ):
        """Student-side scan: validate code then claim attendance."""
        code = code.strip()
        qr = self._qrcodes.get(code)
        if qr is None:
            self._log(code, student_id, "invalid", device_info)
            raise NotFoundError("QR code is invalid.")
        now = utcnow()
        expired = (
            qr.status != "active"
            or (qr.expires_at is not None and now > qr.expires_at)
            or (
                qr.max_uses is not None
                and (qr.used_count or 0) >= qr.max_uses
            )
        )
        if expired:
            self._log(code, student_id, "expired", device_info)
            raise InvalidRegistrationStateError("QR code has expired.")
        session = self._session(qr.schedule_id, qr.session_id)
        if session.status != "open":
            self._log(code, student_id, "invalid", device_info)
            raise InvalidRegistrationStateError(
                "This check-in session is not open."
            )
        registration = self._resolve_registration(
            qr.activity_id, qr.schedule_id, student_id
        )
        if registration is None:
            self._log(code, student_id, "invalid", device_info)
            raise InvalidRegistrationStateError(
                "No approved registration found for this activity."
            )
        if self._attendance.get_for_registration(
            registration.registration_id
        ) is not None:
            self._log(code, student_id, "duplicate", device_info)
            raise AlreadyCheckedInError(
                "This registration was already checked in."
            )
        record = self._attendance.create(
            registration.registration_id, qr.activity_id, student_id,
            session.session_id, "qr", session.created_by, now,
        )
        self._qrcodes.bump_used(code)
        self._log(code, student_id, "accepted", device_info)
        if registration.status == "approved":
            self._registrations.set_status(
                registration.registration_id, "attended",
                student_id, None, now,
            )
            self._registrations.record_history(
                registration.registration_id, "approved", "attended",
                student_id, "check-in via qr session", now,
            )
        if self._events is not None:
            try:
                self._events.attendance_changed(
                    qr.activity_id, "checked_in", record.record_id,
                    student_id, student_id,
                )
            except Exception:  # noqa: BLE001 - realtime is best-effort
                pass
        self._refresh_summary(registration)
        return record

    def _resolve_registration(
        self, activity_id: UUID, schedule_id: UUID, student_id: UUID
    ):
        """Approved/attended registration; prefer one on this schedule."""
        candidates = [
            r
            for r in self._registrations.list_by_student(student_id)
            if r.activity_id == activity_id
            and r.status in ("approved", "attended")
        ]
        if not candidates:
            return None
        if self._slots is not None:
            slot_ids = {
                s.slot_id for s in self._slots.list(schedule_id)
            }
            if slot_ids:
                for r in candidates:
                    if r.slot_id in slot_ids:
                        return r
        return candidates[0]

    def scan_log(
        self, activity_id: UUID, session_id: UUID, viewer_id: UUID
    ) -> list[QrScanLog]:
        """Manager audit feed of every scan on one session's code."""
        activity = self._activity(activity_id)
        self._require_manager(
            activity.org_id, viewer_id, "attendance.scanlog"
        )
        schedule_ids = {
            s.id for s in self._schedules.list(activity_id)
        }
        for schedule_id in schedule_ids:
            session = self._sessions.get(schedule_id, session_id)
            if session is not None:
                return self._scanlogs.list(session.qr_code)
        raise NotFoundError("Session not found.")

    def _sessions_for_registration(self, registration) -> list:
        """Sessions under the registration's slot schedule (or all)."""
        zero = UUID(int=0)
        if (
            registration.slot_id is not None
            and registration.slot_id != zero
            and self._slots is not None
        ):
            slot = next(
                (
                    s
                    for s in self._slots.list_for_activity(
                        registration.activity_id
                    )
                    if s.slot_id == registration.slot_id
                ),
                None,
            )
            if slot is not None:
                return self._sessions.list(slot.schedule_id)
        rows: list = []
        for schedule in self._schedules.list(registration.activity_id):
            rows.extend(self._sessions.list(schedule.id))
        return rows

    def _compute_summary(self, registration) -> dict:
        """Rollup values from live sessions plus the attendance row."""
        sessions = self._sessions_for_registration(registration)
        total = len(sessions)
        record = self._attendance.get_for_registration(
            registration.registration_id
        )
        attended = 0
        minutes = 0
        if record is not None:
            full = self._attendance.get(record.record_id)
            attended = 1
            if full is not None:
                if full.actual_hours is not None:
                    minutes = int(full.actual_hours * 60)
                elif (
                    full.checked_out_at is not None
                    and full.scanned_at is not None
                ):
                    minutes = int(
                        (full.checked_out_at - full.scanned_at)
                        .total_seconds()
                        // 60
                    )
        required = total if total > 0 else 1
        status = "complete" if attended >= required else "incomplete"
        return {
            "sessions_total": total,
            "sessions_attended": attended,
            "minutes_attended": minutes,
            "status": status,
        }

    def _refresh_summary(self, registration) -> None:
        """Best-effort rollup write after a committed scan."""
        if self._summaries is None:
            return
        try:
            rollup = self._compute_summary(registration)
            self._summaries.upsert(
                registration.registration_id,
                registration.activity_id,
                registration.student_id,
                rollup["sessions_total"],
                rollup["sessions_attended"],
                rollup["minutes_attended"],
                rollup["status"],
                utcnow(),
            )
        except Exception:  # noqa: BLE001 - rollups are best-effort
            pass

    def summary(
        self, activity_id: UUID, registration_id: UUID, viewer_id: UUID
    ) -> AttendanceSummary:
        """Live rollup; materializes the row on every read."""
        activity = self._activity(activity_id)
        row = self._registrations.get(registration_id)
        if row is None or row.activity_id != activity_id:
            raise NotFoundError("Registration not found.")
        if row.student_id != viewer_id:
            self._require_manager(
                activity.org_id, viewer_id, "attendance.summary"
            )
        if self._summaries is None:
            raise NotFoundError("Summaries are not available.")
        rollup = self._compute_summary(row)
        return self._summaries.upsert(
            registration_id, activity_id, row.student_id,
            rollup["sessions_total"], rollup["sessions_attended"],
            rollup["minutes_attended"], rollup["status"], utcnow(),
        )
