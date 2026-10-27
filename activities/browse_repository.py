"""cqlengine reads behind the browse feed: bounded clustering-range scans.

Every query pins a partition and ranges over the clustering column start_at,
so nothing needs ALLOW FILTERING. Tag, category and city are not read here:
the facets need the whole window, so the service filters them in memory.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from activities.browse_interfaces import BrowseIndex, CandidateWindow, ScanPlan
from activities.browse_window import Scan, cut_window, org_scans, public_scans
from activities.model import ActivitiesByOrg, ActivitiesByStatus, Activity
from core.event_phase import utc_naive

# Rows kept per flagged source before the window is cut and flagged truncated.
SCAN_LIMIT = 200
# Recently started published rows checked for ongoing and past phases.
RECENT_LIMIT = 100
# Rows read from one organization's feed before its window is cut.
ORG_SCAN_LIMIT = 300
# Only these statuses are public; drafts and cancelled rows never reach a feed.
PUBLIC_STATUSES = frozenset({"published", "ongoing", "completed"})
_IN_CHUNK = 50


def _read(
    model: Any, partition: dict[str, Any], scan: Scan, ascending: bool
) -> list[Any]:
    """Up to limit + 1 rows of one clustering range, in scan order."""
    edges: dict[str, Any] = {}
    if scan.lower is not None:
        op = "gte" if scan.lower.inclusive else "gt"
        edges[f"start_at__{op}"] = scan.lower.value
    if scan.upper is not None:
        op = "lte" if scan.upper.inclusive else "lt"
        edges[f"start_at__{op}"] = scan.upper.value
    ordered = model.objects(**partition, **edges).order_by(
        "start_at" if ascending else "-start_at"
    )
    return list(ordered.limit(scan.limit + 1))


class CqlBrowseIndex(BrowseIndex):
    """Status-feed and organization-feed windows; drafts are filtered later."""

    def candidates(self, plan: ScanPlan) -> CandidateWindow:
        if plan.org_id is not None:
            scans = org_scans(
                str(plan.org_id),
                plan.starts_from,
                plan.starts_to,
                plan.cursor,
                ORG_SCAN_LIMIT,
            )
            ascending = False
            fetched = [
                _read(ActivitiesByOrg, {"org_id": plan.org_id}, scan, ascending)
                for scan in scans
            ]
        else:
            ascending = plan.phase == "upcoming"
            scans = public_scans(
                plan.phase,
                plan.now,
                plan.starts_from,
                plan.starts_to,
                plan.cursor,
                status_limit=SCAN_LIMIT,
                recent_limit=RECENT_LIMIT,
            )
            fetched = [
                _read(
                    ActivitiesByStatus, {"status": scan.partition}, scan, ascending
                )
                for scan in scans
            ]
        rows, cut = cut_window(
            fetched,
            [scan.limit for scan in scans],
            key=lambda row: utc_naive(row.start_at),
            ascending=ascending,
        )
        ids = list(
            dict.fromkeys(row.activity_id for row in rows if row.status in PUBLIC_STATUSES)
        )
        return CandidateWindow(ids=ids, cut=cut)

    def hydrate(self, ids: list[UUID]) -> list[Activity]:
        """One IN query per chunk instead of one read per id."""
        unique = list(dict.fromkeys(ids))
        found: dict[UUID, Activity] = {}
        for start in range(0, len(unique), _IN_CHUNK):
            chunk = unique[start : start + _IN_CHUNK]
            for row in Activity.objects(id__in=chunk):
                found[row.id] = row
        return [found[item] for item in unique if item in found]
