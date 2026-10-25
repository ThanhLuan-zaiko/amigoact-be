"""cqlengine reads behind the browse feed: bounded range scans, no filtering.

Every query uses a partition key plus the clustering column start_at, so
nothing needs ALLOW FILTERING. Tag and category are not read here: the
facets need the whole phase window, so the service filters them in memory.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from cassandra.cqlengine.query import ModelQuerySet

from activities.browse_interfaces import BrowseIndex
from activities.model import ActivitiesByStatus, Activity

# Rows kept per source before the window is cut and flagged truncated.
SCAN_LIMIT = 200
# Recently started published rows checked for ongoing and past phases.
RECENT_LIMIT = 100
_IN_CHUNK = 50

Window = tuple[list[UUID], bool]


def _window(query: ModelQuerySet, limit: int) -> Window:
    """Take one more row than the limit so overflow is detectable."""
    rows = list(query.limit(limit + 1))
    return [row.activity_id for row in rows[:limit]], len(rows) > limit


def _merge(*windows: Window) -> Window:
    ids: list[UUID] = []
    truncated = False
    for part, cut in windows:
        ids.extend(part)
        truncated = truncated or cut
    return list(dict.fromkeys(ids)), truncated


class CqlBrowseIndex(BrowseIndex):
    """Status-feed windows; drafts and cancelled rows are filtered later."""

    def candidates(self, phase: str, now: datetime) -> Window:
        """Upcoming is one ascending range. Ongoing and past combine the
        explicit status partition with recently started published rows,
        because organizers often never flip published to ongoing/completed."""
        if phase == "upcoming":
            return _window(
                ActivitiesByStatus.objects(
                    status="published", start_at__gt=now
                ).order_by("start_at"),
                SCAN_LIMIT,
            )
        flagged = "ongoing" if phase == "ongoing" else "completed"
        return _merge(
            _window(
                ActivitiesByStatus.objects(status=flagged), SCAN_LIMIT
            ),
            _window(
                ActivitiesByStatus.objects(
                    status="published", start_at__lte=now
                ),
                RECENT_LIMIT,
            ),
        )

    def hydrate(self, ids: list[UUID]) -> list[Activity]:
        """One IN query per chunk instead of one read per id."""
        unique = list(dict.fromkeys(ids))
        found: dict[UUID, Activity] = {}
        for start in range(0, len(unique), _IN_CHUNK):
            chunk = unique[start : start + _IN_CHUNK]
            for row in Activity.objects(id__in=chunk):
                found[row.id] = row
        return [found[item] for item in unique if item in found]
