"""Cross-org activity feed for the signed-in user (the /manage/events page).

Every org the caller actively belongs to contributes its rows. Rights are
resolved per org: the owner, activity:manage (edit, trash, purge) and
activity:create (open drafts). Trash is only ever listed for orgs the
caller can manage.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

from activities.interfaces import ActivityStore
from activities.model import Activity
from core.security import utc_aware
from orgs.brand import brand_url
from orgs.interfaces import MediaRepository, OrgRepository
from rbac.implied import holds
from rbac.interfaces import AccessControl

# Per-org read cap, and the total returned to the page after sorting.
PER_ORG_LIMIT = 100
FEED_LIMIT = 300
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class OrgGrant:
    """One org the caller belongs to, with the rights they hold there."""

    org: object
    can_create: bool
    can_manage: bool
    can_delete: bool = False
    activity_count: int = 0
    logo_url: str | None = None


@dataclass(frozen=True)
class FeedRow:
    activity: Activity
    can_manage: bool
    can_delete: bool = False


@dataclass(frozen=True)
class MyFeed:
    orgs: list[OrgGrant]
    rows: list[FeedRow]


def _start_key(row: Activity) -> datetime:
    return utc_aware(row.start_at) or _EPOCH


class MyActivitiesService:
    """Reads the caller's orgs and gates each row by the caller's rights."""

    def __init__(
        self,
        orgs: OrgRepository,
        activities: ActivityStore,
        access: AccessControl,
        media: MediaRepository | None = None,
    ) -> None:
        self._orgs = orgs
        self._activities = activities
        self._access = access
        self._media = media

    def _grant(self, org: object, user_id: UUID) -> OrgGrant:
        owner = getattr(org, "owner_id", None) == user_id
        org_id = org.id  # type: ignore[attr-defined]
        return OrgGrant(
            org=org,
            can_create=owner
            or self._access.has_permission(org_id, user_id, "activity:create"),
            can_manage=owner
            or self._access.has_permission(org_id, user_id, "activity:manage"),
            can_delete=owner
            or holds(self._access, org_id, user_id, "activity:delete"),
            logo_url=brand_url(
                self._media,
                org_id,
                getattr(org, "logo_media_id", None),
                "logo",
            ),
        )

    def _fetch(self, org_id: UUID, trash: bool) -> list[Activity]:
        if trash:
            return self._activities.list_trash(org_id, PER_ORG_LIMIT)
        return [
            row
            for row in self._activities.list_by_org(org_id, PER_ORG_LIMIT)
            if row.deleted_at is None
        ]

    def feed(self, user_id: UUID, trash: bool = False) -> MyFeed:
        """Rows across the caller's orgs, soonest start first."""
        grants = [
            self._grant(org, user_id)
            for org in self._orgs.list_by_user(user_id)
            if getattr(org, "deleted_at", None) is None
        ]
        orgs: list[OrgGrant] = []
        rows: list[FeedRow] = []
        for grant in grants:
            if trash and not grant.can_delete:
                continue
            found = self._fetch(grant.org.id, trash)  # type: ignore[attr-defined]
            orgs.append(replace(grant, activity_count=len(found)))
            rows.extend(
                FeedRow(row, grant.can_manage, grant.can_delete) for row in found
            )
        rows.sort(key=lambda item: _start_key(item.activity))
        return MyFeed(orgs=orgs, rows=rows[:FEED_LIMIT])
