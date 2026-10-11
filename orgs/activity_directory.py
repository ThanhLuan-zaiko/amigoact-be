"""Bridge from the orgs context onto the activities feed tables.

Reads the light ActivitiesByOrg partition (no hydration) to count and
filter, then hydrates only the handful of rows the profile renders.
The public-status mapping lives here because it translates the
activities context's lifecycle vocabulary for org consumers.
"""

from __future__ import annotations

from uuid import UUID

from activities.model import ActivitiesByOrg, Activity
from orgs.interfaces import (
    ActivityDirectory,
    OrgActivityBrief,
    OrgActivityListing,
)

PUBLIC_ACTIVITY_STATUSES: frozenset[str] = frozenset(
    {"published", "ongoing", "completed"}
)
"""Lifecycle states guests may see; drafts and cancelled stays hidden."""

_FEED_SCAN_LIMIT = 500


class CqlOrgActivityDirectory(ActivityDirectory):
    """Feed-row scan plus point hydration for the org profile page."""

    def __init__(self, keyspace: str) -> None:
        self._keyspace = keyspace

    def list_public(self, org_id: UUID, limit: int = 6) -> OrgActivityListing:
        feed = list(
            ActivitiesByOrg.objects(org_id=org_id)
            .limit(_FEED_SCAN_LIMIT)
            .all()
        )
        public = [row for row in feed if row.status in PUBLIC_ACTIVITY_STATUSES]
        rows = {
            row.id: row
            for row in (
                Activity.objects(id=item.activity_id).first()
                for item in public[:limit]
            )
            if row is not None
        }
        items = [
            OrgActivityBrief(
                id=row.id,
                slug=row.slug,
                title=row.title,
                status=row.status,
                city=row.city,
                start_at=row.start_at,
            )
            for item in public[:limit]
            if (row := rows.get(item.activity_id)) is not None
        ]
        return OrgActivityListing(total=len(public), items=items)
