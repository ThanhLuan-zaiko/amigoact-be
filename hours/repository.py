"""cqlengine persistence for the volunteer-hours ledger and feeds."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from hours.interfaces import (
    AdjustmentStore,
    HourLedgerStore,
    HourRuleStore,
    LeaderboardStore,
)
from hours.model import (
    HourAdjustment,
    HourEntriesByStudent,
    HourRule,
    HoursByActivity,
    HoursByStudent,
    LeaderboardByTerm,
    LeaderboardTerm,
    PendingHoursByOrg,
    VolunteerHourEntry,
)


def _sync_feeds(
    entry: VolunteerHourEntry, org_id: UUID, status: str
) -> None:
    """Mirror status across activity/student feeds + queue lifecycle."""
    HoursByActivity.objects(
        activity_id=entry.activity_id,
        recorded_at=entry.recorded_at,
        entry_id=entry.entry_id,
    ).update(
        student_id=entry.student_id,
        hours=entry.hours,
        status=status,
    )
    HourEntriesByStudent.objects(
        student_id=entry.student_id,
        recorded_at=entry.recorded_at,
        entry_id=entry.entry_id,
    ).update(
        activity_id=entry.activity_id,
        hours=entry.hours,
        source=entry.source,
        status=status,
    )
    if status == "pending":
        PendingHoursByOrg.objects(
            org_id=org_id,
            recorded_at=entry.recorded_at,
            entry_id=entry.entry_id,
        ).update(
            student_id=entry.student_id,
            activity_id=entry.activity_id,
            hours=entry.hours,
        )
    else:
        PendingHoursByOrg.objects(
            org_id=org_id,
            recorded_at=entry.recorded_at,
            entry_id=entry.entry_id,
        ).delete()


def _rollup_approve(entry: VolunteerHourEntry, now: datetime) -> None:
    """Add approved hours to the student's per-term summary."""
    try:
        row = HoursByStudent.get(
            student_id=entry.student_id, term=entry.term
        )
    except HoursByStudent.DoesNotExist:
        row = None
    total = (row.total_hours if row else 0.0) + entry.hours
    count = (row.activities_count if row else 0) + 1
    HoursByStudent.objects(
        student_id=entry.student_id, term=entry.term
    ).update(
        total_hours=total,
        activities_count=count,
        updated_at=now,
    )


class CqlHourLedgerStore(HourLedgerStore):
    """Ledger aggregate plus queue/feed/rollup projections."""

    def __init__(self, keyspace: str) -> None:
        self._keyspace = keyspace

    def record(
        self,
        entry_id: UUID,
        org_id: UUID,
        student_id: UUID,
        activity_id: UUID,
        source: str,
        hours: float,
        term: str,
        registration_id: UUID | None,
        recorded_by: UUID | None,
        note: str | None,
        now: datetime,
    ) -> VolunteerHourEntry:
        entry = VolunteerHourEntry.create(
            entry_id=entry_id,
            student_id=student_id,
            activity_id=activity_id,
            source=source,
            hours=hours,
            term=term,
            registration_id=registration_id,
            status="pending",
            recorded_at=now,
            recorded_by=recorded_by,
            note=note,
        )
        _sync_feeds(entry, org_id, "pending")
        return entry

    def get(self, entry_id: UUID) -> VolunteerHourEntry | None:
        try:
            return VolunteerHourEntry.get(entry_id=entry_id)
        except VolunteerHourEntry.DoesNotExist:
            return None

    def set_status(
        self,
        entry: VolunteerHourEntry,
        org_id: UUID,
        status: str,
        reviewer_id: UUID,
        now: datetime,
    ) -> VolunteerHourEntry:
        VolunteerHourEntry.objects(entry_id=entry.entry_id).update(
            status=status,
            approved_by=reviewer_id,
            approved_at=now,
        )
        _sync_feeds(entry, org_id, status)
        if status == "approved":
            _rollup_approve(entry, now)
        updated = self.get(entry.entry_id)
        assert updated is not None
        return updated

    def list_pending(
        self, org_id: UUID, limit: int = 100
    ) -> list[PendingHoursByOrg]:
        return list(
            PendingHoursByOrg.objects(org_id=org_id).limit(limit)
        )

    def list_by_student(
        self, student_id: UUID, limit: int = 100
    ) -> list[HourEntriesByStudent]:
        return list(
            HourEntriesByStudent.objects(student_id=student_id).limit(
                limit
            )
        )

    def list_by_activity(
        self, activity_id: UUID, limit: int = 100
    ) -> list[HoursByActivity]:
        return list(
            HoursByActivity.objects(activity_id=activity_id).limit(
                limit
            )
        )

    def summary_for_student(
        self, student_id: UUID
    ) -> list[HoursByStudent]:
        return list(HoursByStudent.objects(student_id=student_id))


class CqlLeaderboardStore(LeaderboardStore):
    """Moves leaderboard rows so reads stay sorted without filtering."""

    def put(
        self,
        term: str,
        student_id: UUID,
        student_name: str,
        previous_total: float,
        new_total: float,
        now: datetime,
    ) -> None:
        if previous_total > 0 and previous_total != new_total:
            LeaderboardByTerm.objects(
                term=term,
                total_hours=previous_total,
                student_id=student_id,
            ).delete()
        LeaderboardByTerm.objects(
            term=term,
            total_hours=new_total,
            student_id=student_id,
        ).update(student_name=student_name, updated_at=now)
        LeaderboardTerm.create(term=term)

    def top(
        self, term: str, limit: int = 50
    ) -> list[LeaderboardByTerm]:
        return list(
            LeaderboardByTerm.objects(term=term).limit(limit)
        )

    def terms(self) -> list[str]:
        return sorted(
            row.term for row in LeaderboardTerm.objects().all()
        )


class CqlHourRuleStore(HourRuleStore):
    """Rule CRUD over the singleton-PK table via the org index."""

    def create(
        self,
        rule_id: UUID,
        org_id: UUID,
        category_id: UUID | None,
        multiplier: float,
        cap_hours: float | None,
        term: str | None,
    ) -> HourRule:
        return HourRule.create(
            rule_id=rule_id,
            org_id=org_id,
            category_id=category_id,
            multiplier=multiplier,
            cap_hours=cap_hours,
            term=term,
            is_active=True,
        )

    def get(self, rule_id: UUID) -> HourRule | None:
        try:
            return HourRule.get(rule_id=rule_id)
        except HourRule.DoesNotExist:
            return None

    def list_by_org(self, org_id: UUID) -> list[HourRule]:
        return list(HourRule.objects(org_id=org_id).all())

    def set_active(
        self, rule_id: UUID, is_active: bool
    ) -> HourRule | None:
        if self.get(rule_id) is None:
            return None
        HourRule.objects(rule_id=rule_id).update(is_active=is_active)
        return self.get(rule_id)


class CqlAdjustmentStore(AdjustmentStore):
    """Append-only audit rows for staff corrections."""

    def create(
        self,
        adjustment_id: UUID,
        student_id: UUID,
        activity_id: UUID,
        delta_hours: float,
        reason: str,
        created_by: UUID,
        now: datetime,
    ) -> HourAdjustment:
        return HourAdjustment.create(
            adjustment_id=adjustment_id,
            student_id=student_id,
            activity_id=activity_id,
            delta_hours=delta_hours,
            reason=reason,
            created_by=created_by,
            created_at=now,
        )

    def get(self, adjustment_id: UUID) -> HourAdjustment | None:
        try:
            return HourAdjustment.get(adjustment_id=adjustment_id)
        except HourAdjustment.DoesNotExist:
            return None
