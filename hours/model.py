"""cqlengine models for the volunteer-hours ledger and its feeds."""

from __future__ import annotations

import core.database  # noqa: F401  (reactor compat shim must run first)
from core.ids import uuid7
from cassandra.cqlengine import columns, models


class VolunteerHourEntry(models.Model):
    """Authoritative append-only ledger row."""

    __table_name__ = "volunteer_hour_ledger"

    entry_id = columns.UUID(primary_key=True, default=uuid7)
    student_id = columns.UUID(required=True)
    activity_id = columns.UUID(required=True)
    source = columns.Text(required=True)  # attendance | manual | adjustment
    hours = columns.Double(required=True)
    term = columns.Text(required=True)
    registration_id = columns.UUID()
    status = columns.Text(required=True)  # pending | approved | rejected
    approved_by = columns.UUID()
    approved_at = columns.DateTime()
    recorded_at = columns.DateTime(required=True)
    recorded_by = columns.UUID()
    note = columns.Text()


class HoursByStudent(models.Model):
    """Approved-hours rollup per student per term."""

    __table_name__ = "hours_by_student"

    student_id = columns.UUID(primary_key=True)
    term = columns.Text(primary_key=True)
    total_hours = columns.Double()
    activities_count = columns.Integer()
    updated_at = columns.DateTime()


class HoursByActivity(models.Model):
    """Per-activity ledger feed for reports, newest first."""

    __table_name__ = "hours_by_activity"

    activity_id = columns.UUID(primary_key=True)
    recorded_at = columns.DateTime(
        primary_key=True, clustering_order="DESC"
    )
    entry_id = columns.UUID(
        primary_key=True, clustering_order="ASC"
    )
    student_id = columns.UUID()
    hours = columns.Double()
    status = columns.Text()


class PendingHoursByOrg(models.Model):
    """Manager approval queue: pending entries, oldest first."""

    __table_name__ = "pending_hours_by_org"

    org_id = columns.UUID(primary_key=True)
    recorded_at = columns.DateTime(
        primary_key=True, clustering_order="ASC"
    )
    entry_id = columns.UUID(
        primary_key=True, clustering_order="ASC"
    )
    student_id = columns.UUID()
    activity_id = columns.UUID()
    hours = columns.Double()


class HourEntriesByStudent(models.Model):
    """Student-facing ledger history (canonical ledger keys entry_id only,
    so this feed keeps per-student reads partition-local)."""

    __table_name__ = "hour_entries_by_student"

    student_id = columns.UUID(primary_key=True)
    recorded_at = columns.DateTime(
        primary_key=True, clustering_order="DESC"
    )
    entry_id = columns.UUID(
        primary_key=True, clustering_order="ASC"
    )
    activity_id = columns.UUID()
    hours = columns.Double()
    source = columns.Text()
    status = columns.Text()


class LeaderboardByTerm(models.Model):
    """Ranked student hours per term (term='all' is the all-time board)."""

    __table_name__ = "leaderboard_by_term"

    term = columns.Text(primary_key=True)
    total_hours = columns.Double(
        primary_key=True, clustering_order="DESC"
    )
    student_id = columns.UUID(
        primary_key=True, clustering_order="ASC"
    )
    student_name = columns.Text()
    updated_at = columns.DateTime()


class LeaderboardTerm(models.Model):
    """Distinct term list for leaderboard filters."""

    __table_name__ = "leaderboard_terms"

    term = columns.Text(primary_key=True)


class HourAdjustment(models.Model):
    """Staff correction rows (kept for audit trail)."""

    __table_name__ = "hour_adjustments"

    adjustment_id = columns.UUID(primary_key=True, default=uuid7)
    student_id = columns.UUID()
    activity_id = columns.UUID()
    delta_hours = columns.Double()
    reason = columns.Text()
    created_by = columns.UUID()
    created_at = columns.DateTime()


class HourRule(models.Model):
    """Per-org multiplier/cap applied to recorded attendance hours."""

    __table_name__ = "hour_rules"

    rule_id = columns.UUID(primary_key=True, default=uuid7)
    org_id = columns.UUID(index=True)
    category_id = columns.UUID()
    multiplier = columns.Double()
    cap_hours = columns.Double()
    term = columns.Text()
    is_active = columns.Boolean()
