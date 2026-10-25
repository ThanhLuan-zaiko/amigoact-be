"""Pre-aggregated stats tables materialized from live feeds."""

from __future__ import annotations

import core.database  # noqa: F401  (reactor compat shim must run first)
from cassandra.cqlengine import columns, models


class ActivityDailyStats(models.Model):
    """Per-activity per-day rollup (registrations/attendees/hours)."""

    __table_name__ = "activity_daily_stats"

    activity_id = columns.UUID(primary_key=True, partition_key=True)
    day = columns.Date(primary_key=True, clustering_order="DESC")
    registrations = columns.Integer(required=False, default=0)
    attendees = columns.Integer(required=False, default=0)
    hours_awarded = columns.Double(required=False, default=0.0)


class OrgMonthlyStats(models.Model):
    """Per-org per-month rollup over activities/participants/hours/certs."""

    __table_name__ = "org_monthly_stats"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    month = columns.Text(primary_key=True, clustering_order="DESC")
    activities = columns.Integer(required=False, default=0)
    participants = columns.Integer(required=False, default=0)
    hours = columns.Double(required=False, default=0.0)
    certificates = columns.Integer(required=False, default=0)
