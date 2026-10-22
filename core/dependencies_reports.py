"""Depends wiring for the reports/export feature (split for the 350-line rule)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.config import get_settings
from core.dependencies import get_access_control, user_directory

if TYPE_CHECKING:
    from reports.service import ReportService


def get_report_service() -> "ReportService":
    """Build one ReportService per request."""
    from core.durability import CqlJobLeaseStore
    from orgs.repository import CqlOrgRepository
    from registrations.repository import CqlRegistrationStore
    from reports.repository import CqlExportJobStore, CqlReportStore
    from reports.service import ReportService
    from stats.repository import CqlMonthlyStatsStore

    settings = get_settings()
    return ReportService(
        snapshots=CqlReportStore(),
        jobs=CqlExportJobStore(),
        monthly=CqlMonthlyStatsStore(),
        registrations=CqlRegistrationStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        access=get_access_control(),
        users=user_directory(settings),
        leases=CqlJobLeaseStore(settings.scylla_keyspace),
    )
