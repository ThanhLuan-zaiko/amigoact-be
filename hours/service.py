"""Volunteer-hours business rules (no FastAPI, no CQL)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from activities.interfaces import ActivityStore
from core.exceptions import (
    ForbiddenError,
    InvalidHoursStateError,
    NotFoundError,
)
from core.ids import uuid7
from core.security import utcnow
from hours.interfaces import (
    HourLedgerStore,
    HourRecorder,
    HourRuleStore,
    LeaderboardStore,
)
from hours.model import (
    HourEntriesByStudent,
    LeaderboardByTerm,
    PendingHoursByOrg,
    VolunteerHourEntry,
)
from notifications.interfaces import NotificationPort
from orgs.interfaces import OrgRepository, UserDirectory
from rbac.interfaces import AccessControl


def term_of(moment: datetime) -> str:
    """Half-year bucket: '2026-H1' | '2026-H2'."""
    return f"{moment.year}-H{1 if moment.month <= 6 else 2}"


@dataclass(frozen=True)
class StudentHoursSummary:
    """One approved-hours rollup row per term."""

    term: str
    total_hours: float
    activities_count: int


class HourService(HourRecorder):
    """Ledger writes, the org approval queue, and student rollups."""

    def __init__(
        self,
        ledger: HourLedgerStore,
        activities: ActivityStore,
        orgs: OrgRepository,
        access: AccessControl,
        notifications: NotificationPort | None = None,
        leaderboard: LeaderboardStore | None = None,
        users: UserDirectory | None = None,
        rules: HourRuleStore | None = None,
    ) -> None:
        self._ledger = ledger
        self._activities = activities
        self._orgs = orgs
        self._access = access
        self._notifications = notifications
        self._leaderboard = leaderboard
        self._users = users
        self._rules = rules

    def _require_manager(self, org_id: UUID, actor: UUID, action: str) -> None:
        org = self._orgs.get_by_id(org_id)
        if org is None or getattr(org, "deleted_at", None) is not None:
            raise NotFoundError("Organization not found.")
        if (
            getattr(org, "owner_id", None) != actor
            and not self._access.has_permission(
                org_id, actor, "activity:manage"
            )
        ):
            self._access.record(
                org_id, actor, action, "hour_entry", None, "denied"
            )
            raise ForbiddenError("Only org managers can do this.")

    def _notify(self, user_id: UUID, title: str, body: str = "") -> None:
        if self._notifications is None:
            return
        try:
            self._notifications.notify(
                user_id, "hours", title, body, None
            )
        except Exception:  # noqa: BLE001 - notifications are best-effort
            pass

    # HourRecorder port -------------------------------------------------

    def record_attendance(
        self,
        org_id: UUID,
        activity_id: UUID,
        student_id: UUID,
        registration_id: UUID | None,
        hours: float,
        recorded_by: UUID,
    ) -> None:
        """Queue the check-out hours for manager approval."""
        now = utcnow()
        term = term_of(now)
        hours = self._apply_rule(org_id, activity_id, term, hours)
        self._ledger.record(
            uuid7(), org_id, student_id, activity_id,
            "attendance", hours, term, registration_id,
            recorded_by, None, now,
        )

    def _apply_rule(
        self,
        org_id: UUID,
        activity_id: UUID,
        term: str,
        hours: float,
    ) -> float:
        """Best-effort rule lookup; raw hours on any failure."""
        if self._rules is None:
            return hours
        try:
            from hours.rule_service import apply_rule

            activity = self._activities.get(activity_id)
            category_id = (
                getattr(activity, "category_id", None)
                if activity is not None
                else None
            )
            return apply_rule(
                self._rules.list_by_org(org_id),
                category_id, term, hours,
            )
        except Exception:  # noqa: BLE001 - rules are best-effort
            return hours

    # Manager flows -----------------------------------------------------

    def submit_manual(
        self,
        org_id: UUID,
        activity_id: UUID,
        student_id: UUID,
        hours: float,
        note: str | None,
        staff_id: UUID,
    ) -> VolunteerHourEntry:
        """Staff-entered hours still require approval like attendance."""
        if hours <= 0:
            raise InvalidHoursStateError("Hours must be positive.")
        self._require_manager(org_id, staff_id, "hours.manual")
        activity = self._activities.get(activity_id)
        if activity is None or activity.org_id != org_id:
            raise NotFoundError("Activity not found.")
        now = utcnow()
        entry = self._ledger.record(
            uuid7(), org_id, student_id, activity_id,
            "manual", hours, term_of(now), None, staff_id, note, now,
        )
        self._access.record(
            org_id, staff_id, "hours.manual", "hour_entry",
            entry.entry_id, "allowed",
        )
        return entry

    def pending_queue(
        self, org_id: UUID, staff_id: UUID
    ) -> list[PendingHoursByOrg]:
        """Oldest-first queue awaiting review."""
        self._require_manager(org_id, staff_id, "hours.queue")
        return self._ledger.list_pending(org_id)

    def review(
        self,
        entry_id: UUID,
        staff_id: UUID,
        status: str,
        note: str | None,
    ) -> VolunteerHourEntry:
        """Approve or reject; approval rolls up per-term summaries."""
        if status not in {"approved", "rejected"}:
            raise InvalidHoursStateError(
                "Review target must be approved|rejected."
            )
        entry = self._ledger.get(entry_id)
        if entry is None:
            raise NotFoundError("Hour entry not found.")
        activity = self._activities.get(entry.activity_id)
        if activity is None:
            raise NotFoundError("Activity not found.")
        self._require_manager(
            activity.org_id, staff_id, "hours.review"
        )
        if entry.status != "pending":
            raise InvalidHoursStateError(
                f"Entry already {entry.status}."
            )
        now = utcnow()
        before = (
            {
                row.term: row.total_hours or 0.0
                for row in self._ledger.summary_for_student(
                    entry.student_id
                )
            }
            if status == "approved"
            else {}
        )
        updated = self._ledger.set_status(
            entry, activity.org_id, status, staff_id, now
        )
        if status == "approved":
            self._rank(entry, before, now)
        self._access.record(
            activity.org_id, staff_id, f"hours.{status}",
            "hour_entry", entry_id, "allowed",
        )
        label = "\u0111\u01b0\u1ee3c duy\u1ec7t" if status == "approved" else "b\u1ecb t\u1eeb ch\u1ed1i"
        self._notify(
            entry.student_id,
            f"Gi\u1edd t\u00ecnh nguy\u1ec7n {label}",
            f"{entry.hours} gi\u1edd c\u1ee7a b\u1ea1n {label}.",
        )
        return updated

    def _rank(
        self,
        entry: VolunteerHourEntry,
        before: dict[str, float],
        now: datetime,
    ) -> None:
        """Move the student on the term and all-time boards (best-effort)."""
        if self._leaderboard is None:
            return
        name = entry.student_id.hex[:12]
        if self._users is not None:
            brief = self._users.get_brief(entry.student_id)
            if brief is not None and brief.full_name:
                name = brief.full_name
        old_term = before.get(entry.term, 0.0)
        old_all = sum(before.values())
        try:
            self._leaderboard.put(
                entry.term, entry.student_id, name,
                old_term, old_term + entry.hours, now,
            )
            self._leaderboard.put(
                "all", entry.student_id, name,
                old_all, old_all + entry.hours, now,
            )
        except Exception:  # noqa: BLE001 - ranking is best-effort
            pass

    # Leaderboard reads --------------------------------------------------

    def leaderboard_top(
        self, term: str = "all", limit: int = 50
    ) -> list[LeaderboardByTerm]:
        """Public ranked rows for one term board."""
        if self._leaderboard is None:
            return []
        return self._leaderboard.top(term, limit)

    def leaderboard_terms(self) -> list[str]:
        """Public list of boards that have at least one entry."""
        if self._leaderboard is None:
            return []
        return self._leaderboard.terms()

    # Student / org reads ------------------------------------------------

    def my_ledger(
        self, student_id: UUID
    ) -> list[HourEntriesByStudent]:
        """Student's full ledger history, newest first."""
        return self._ledger.list_by_student(student_id)

    def my_summary(self, student_id: UUID) -> list[StudentHoursSummary]:
        """Approved totals per term (approved rows only)."""
        return [
            StudentHoursSummary(
                term=row.term,
                total_hours=row.total_hours or 0.0,
                activities_count=row.activities_count or 0,
            )
            for row in self._ledger.summary_for_student(student_id)
        ]

    def activity_ledger(
        self, org_id: UUID, activity_id: UUID, staff_id: UUID
    ) -> list[VolunteerHourEntry]:
        """Manager feed of one activity's ledger entries."""
        self._require_manager(org_id, staff_id, "hours.list")
        activity = self._activities.get(activity_id)
        if activity is None or activity.org_id != org_id:
            raise NotFoundError("Activity not found.")
        rows = self._ledger.list_by_activity(activity_id)
        out: list[VolunteerHourEntry] = []
        for feed_row in rows:
            entry = self._ledger.get(feed_row.entry_id)
            if entry is not None:
                out.append(entry)
        return out
