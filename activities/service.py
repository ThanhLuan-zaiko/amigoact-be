"""Activity lifecycle business rules: create, edit, publish, read."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from activities.interfaces import (
    ActivityEvents,
    ActivityFields,
    ActivityStore,
    CategoryStore,
)
from activities.model import Activity
from activities.model import tag_slug as _tag_key
from activities.tag_claim import (
    PersonalTagBook,
    bind_activity_tags,
    claim_activity_tags,
)
from activities.tag_service import TagService
from core.exceptions import (
    ActivityDeletedError,
    ForbiddenError,
    InvalidOrgStateError,
    NotFoundError,
)
from core.security import utcnow
from orgs.interfaces import OrgRepository
from rbac.implied import holds
from rbac.interfaces import AccessControl

_PUBLIC_STATUSES = {"published", "ongoing", "completed"}
_LIFECYCLE: dict[str, set[str]] = {
    "draft": {"published", "cancelled"},
    "published": {"ongoing", "completed", "cancelled"},
    "ongoing": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


@dataclass(frozen=True)
class CategoryBucket:
    """One discovery shelf: a category plus a few public activities."""

    id: UUID
    name: str
    items: list


@dataclass(frozen=True)
class DiscoveryView:
    """Curated sections for the public discovery page."""

    featured: list
    upcoming: list
    categories: list[CategoryBucket]


class ActivityService:
    """Lifecycle plus read paths; managers act inside their org only."""

    def __init__(
        self,
        activities: ActivityStore,
        categories: CategoryStore,
        orgs: OrgRepository,
        access: AccessControl,
        tags: TagService,
        events: ActivityEvents | None = None,
        user_tags: PersonalTagBook | None = None,
    ) -> None:
        self._activities = activities
        self._categories = categories
        self._orgs = orgs
        self._access = access
        self._events = events
        self._tags = tags
        self._user_tags = user_tags

    def _emit(
        self,
        org_id: UUID,
        action: str,
        activity_id: UUID,
        actor_id: UUID,
        status: str,
    ) -> None:
        """Best-effort fan-out; a dead bus never blocks a mutation."""
        if self._events is None:
            return
        try:
            self._events.activity_changed(
                org_id, action, activity_id, actor_id, status
            )
        except Exception:  # noqa: BLE001 - live fan-out is advisory
            pass

    def _org(self, org_id: UUID) -> object:
        org = self._orgs.get_by_id(org_id)
        if org is None or getattr(org, "deleted_at", None) is not None:
            raise NotFoundError("Organization not found.")
        return org

    def _require_manager(
        self, org_id: UUID, actor_id: UUID, permission: str
    ) -> object:
        """Owner bypass plus RBAC permission for everything else."""
        org = self._org(org_id)
        if (
            getattr(org, "owner_id", None) != actor_id
            and not holds(self._access, org_id, actor_id, permission)
        ):
            self._access.record(
                org_id, actor_id, permission, "activity", None, "denied"
            )
            raise ForbiddenError("Only org managers can do this.")
        return org

    def _is_member(self, org_id: UUID, user_id: UUID | None) -> bool:
        return user_id is not None and self._orgs.is_member(org_id, user_id)

    def _org_activity(self, org_id: UUID, activity_id: UUID) -> Activity:
        row = self._activities.get(activity_id)
        if row is None or row.org_id != org_id:
            raise NotFoundError("Activity not found.")
        return row

    def _check_category(
        self, org_id: UUID, category_id: UUID | None
    ) -> None:
        """Reject category ids that don't exist or belong to another org."""
        if category_id is None:
            return
        category = self._categories.get(category_id)
        if category is None or (
            category.org_id is not None and category.org_id != org_id
        ):
            raise NotFoundError("Category not found.")

    def create_activity(
        self, org_id: UUID, actor_id: UUID, fields: ActivityFields
    ) -> Activity:
        """Member with activity:create opens a draft."""
        self._require_manager(org_id, actor_id, "activity:create")
        self._check_category(org_id, fields.category_id)
        fields.tag_names = claim_activity_tags(
            self._tags, self._user_tags, org_id, actor_id, fields.tag_names
        )
        row = self._activities.create(org_id, actor_id, fields, utcnow())
        bind_activity_tags(
            self._user_tags, actor_id, org_id, row.id, fields.tag_names
        )
        self._access.record(
            org_id, actor_id, "activity.create", "activity", row.id,
            "allowed",
        )
        self._emit(org_id, "created", row.id, actor_id, row.status)
        return row

    def update_activity(
        self,
        org_id: UUID,
        activity_id: UUID,
        actor_id: UUID,
        fields: ActivityFields,
    ) -> Activity:
        """Replace editable fields while the activity is editable."""
        self._require_manager(org_id, actor_id, "activity:manage")
        row = self._org_activity(org_id, activity_id)
        if row.deleted_at is not None:
            raise ActivityDeletedError("Activity is soft-deleted.")
        if row.status in {"completed", "cancelled"}:
            raise InvalidOrgStateError(
                "Completed or cancelled activities cannot be edited."
            )
        self._check_category(org_id, fields.category_id)
        owner_id = row.created_by
        fields.tag_names = claim_activity_tags(
            self._tags, self._user_tags, org_id, owner_id, fields.tag_names
        )
        fields.slug = fields.slug or row.slug
        updated = self._activities.update_details(
            activity_id, fields, utcnow()
        )
        assert updated is not None
        bind_activity_tags(
            self._user_tags, owner_id, org_id, activity_id, fields.tag_names
        )
        self._access.record(
            org_id, actor_id, "activity.update", "activity", activity_id,
            "allowed",
        )
        self._emit(
            org_id, "updated", activity_id, actor_id, updated.status
        )
        return updated

    def set_status(
        self,
        org_id: UUID,
        activity_id: UUID,
        actor_id: UUID,
        target: str,
    ) -> Activity:
        """Move the lifecycle forward along the allowed edges."""
        self._require_manager(org_id, actor_id, "activity:manage")
        row = self._org_activity(org_id, activity_id)
        if row.deleted_at is not None:
            raise ActivityDeletedError("Activity is soft-deleted.")
        if target not in _LIFECYCLE.get(row.status, set()):
            raise InvalidOrgStateError(
                f"Cannot move {row.status} to {target}."
            )
        now = utcnow()
        published_at = now if target == "published" else None
        updated = self._activities.set_status(
            activity_id, target, published_at, now
        )
        assert updated is not None
        self._access.record(
            org_id, actor_id, f"activity.{target}", "activity",
            activity_id, "allowed",
        )
        self._emit(org_id, target, activity_id, actor_id, updated.status)
        return updated

    def get_visible(
        self, activity_id: UUID, viewer_id: UUID | None
    ) -> Activity:
        """Public statuses for anyone; drafts only for org members."""
        row = self._activities.get(activity_id)
        if row is None or row.deleted_at is not None:
            raise NotFoundError("Activity not found.")
        if row.status not in _PUBLIC_STATUSES and not self._is_member(
            row.org_id, viewer_id
        ):
            raise NotFoundError("Activity not found.")
        return row

    def get_by_slug(
        self, org_id: UUID, slug: str, viewer_id: UUID | None
    ) -> Activity:
        """Pretty-URL resolution with the same visibility rules."""
        org = self._orgs.get_by_id(org_id)
        if org is None:
            raise NotFoundError("Organization not found.")
        index = self._activities.get_by_slug(org_id, slug)
        if index is None:
            raise NotFoundError("Activity not found.")
        return self.get_visible(index.activity_id, viewer_id)

    def list_org(
        self, org_id: UUID, viewer_id: UUID, trash: bool = False
    ) -> list[Activity]:
        """Org feed for members; trash lists are manager-only."""
        self._org(org_id)
        if trash:
            self._require_manager(org_id, viewer_id, "activity:delete")
            return self._activities.list_trash(org_id)
        if not self._is_member(org_id, viewer_id):
            raise ForbiddenError(
                "Only org members can list activities."
            )
        return [
            row
            for row in self._activities.list_by_org(org_id)
            if row.deleted_at is None
        ]

    def list_public(
        self,
        status: str = "published",
        category_id: UUID | None = None,
        limit: int = 50,
        tag_slug: str | None = None,
    ) -> list[Activity]:
        """Discovery feed; only public lifecycle states are served."""
        if status not in _PUBLIC_STATUSES:
            raise InvalidOrgStateError("Status filter is not public.")
        if tag_slug is not None:
            return [
                row
                for row in self._activities.list_by_tag(
                    _tag_key(tag_slug), limit
                )
                if row.status == status
                and row.deleted_at is None
                and (category_id is None or row.category_id == category_id)
            ]
        if category_id is not None:
            # Drafts share this feed (no status column); filter them here.
            found = self._activities.list_by_category(category_id, limit)
            return [row for row in found if row.status == status and row.deleted_at is None]
        return [
            row
            for row in self._activities.list_by_status(status, limit)
            if row.deleted_at is None
        ]

    def discovery(self, limit: int = 6) -> DiscoveryView:
        """Curated shelves: ongoing/published highlights, soonest starts,
        and a few items per non-empty global category."""
        published = [
            row
            for row in self._activities.list_by_status("published", 50)
            if row.deleted_at is None
        ]
        ongoing = [
            row
            for row in self._activities.list_by_status("ongoing", 20)
            if row.deleted_at is None
        ]
        # Stored timestamps come back naive UTC; normalize both sides so
        # aware values (fakes, other sources) compare the same way.
        now = utcnow().replace(tzinfo=None)

        def naive(value: datetime) -> datetime:
            return value.replace(tzinfo=None)

        upcoming = sorted(
            (
                row
                for row in published
                if row.start_at is not None and naive(row.start_at) >= now
            ),
            key=lambda row: naive(row.start_at),
        )[:limit]
        featured = (ongoing + published)[:limit]
        buckets: list[CategoryBucket] = []
        for cat in self._categories.list(None):
            if len(buckets) >= limit:
                break
            items = [
                row
                for row in self._activities.list_by_category(cat.id, 4)
                if row.status in _PUBLIC_STATUSES
                and row.deleted_at is None
            ]
            if items:
                buckets.append(
                    CategoryBucket(id=cat.id, name=cat.name, items=items)
                )
        return DiscoveryView(
            featured=featured, upcoming=upcoming, categories=buckets
        )
