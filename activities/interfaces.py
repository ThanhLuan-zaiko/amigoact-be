"""Abstract ports for the activities bounded context (DIP wiring)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from activities.model import (
    ActivitiesBySlug,
    Activity,
    ActivityCategory,
)
from activities.tag_model import PublicTagDirectory, TagByOrg


class ActivityFields:
    """Flat bag of the editable activity fields (create/update share it)."""

    def __init__(  # noqa: PLR0913  (field bag is the point)
        self,
        *,
        title: str,
        slug: str | None,
        description: str | None,
        category_id: UUID | None,
        location: str | None,
        address: str | None,
        city: str | None,
        latitude: Decimal | None,
        longitude: Decimal | None,
        is_remote: bool,
        max_participants: int | None,
        start_at: datetime,
        end_at: datetime | None,
        hours_awarded: float,
        requirements_json: str | None,
        registration_deadline: datetime | None,
        person_in_charge_id: UUID | None,
        campus_id: UUID | None = None,
        tag_names: list[str] | None = None,
    ) -> None:
        self.title = title
        self.slug = slug
        self.description = description
        self.category_id = category_id
        self.location = location
        self.address = address
        self.city = city
        self.latitude = latitude
        self.longitude = longitude
        self.is_remote = is_remote
        self.max_participants = max_participants
        self.start_at = start_at
        self.end_at = end_at
        self.hours_awarded = hours_awarded
        self.requirements_json = requirements_json
        self.registration_deadline = registration_deadline
        self.person_in_charge_id = person_in_charge_id
        self.campus_id = campus_id
        self.tag_names = tag_names or []


class ActivityStore(ABC):
    """Persistence port for the activity aggregate plus its feeds."""

    @abstractmethod
    def create(
        self,
        org_id: UUID,
        created_by: UUID,
        fields: ActivityFields,
        now: datetime,
    ) -> Activity:
        """Insert the row plus every denormalized feed projection."""

    @abstractmethod
    def get(self, activity_id: UUID) -> Activity | None:
        """Load one activity by primary key."""

    @abstractmethod
    def get_by_slug(
        self, org_id: UUID, slug: str
    ) -> ActivitiesBySlug | None:
        """Resolve a pretty slug inside one org."""

    @abstractmethod
    def update_details(
        self, activity_id: UUID, fields: ActivityFields, now: datetime
    ) -> Activity | None:
        """Replace editable fields and rewrite changed feed rows."""

    @abstractmethod
    def set_status(
        self,
        activity_id: UUID,
        status: str,
        published_at: datetime | None,
        now: datetime,
    ) -> Activity | None:
        """Flip lifecycle status and re-partition the status feed."""

    @abstractmethod
    def list_by_org(
        self, org_id: UUID, limit: int = 50
    ) -> list[Activity]:
        """Org feed rows resolved to full activities, newest first."""

    @abstractmethod
    def list_by_status(
        self, status: str, limit: int = 50
    ) -> list[Activity]:
        """Public feed: newest-first activities in one lifecycle state."""

    @abstractmethod
    def list_by_category(
        self, category_id: UUID, limit: int = 50
    ) -> list[Activity]:
        """Public feed filtered to one catalog category."""

    @abstractmethod
    def list_by_tag(
        self, tag_slug: str, limit: int = 50
    ) -> list[Activity]:
        """Public feed filtered to one community tag slug."""

    @abstractmethod
    def mark_deleted(
        self, activity_id: UUID, now: datetime
    ) -> Activity | None:
        """Soft delete: clear feeds into the trash bin; slug stays claimed."""

    @abstractmethod
    def mark_restored(
        self, activity_id: UUID, now: datetime
    ) -> Activity | None:
        """Clear deleted_at and rewrite every feed projection."""

    @abstractmethod
    def list_trash(self, org_id: UUID, limit: int = 50) -> list[Activity]:
        """Manager-only trash listing, newest deletions first."""

    @abstractmethod
    def delete_everything(self, activity_id: UUID) -> list[str]:
        """Purge the row, every feed and edge, plus media rows; returns
        the file_urls whose bytes still sit on disk."""


class CategoryStore(ABC):
    """Persistence port for the activity category catalog."""

    @abstractmethod
    def get(self, category_id: UUID) -> ActivityCategory | None:
        """Load one category by primary key."""

    @abstractmethod
    def list(self, org_id: UUID | None) -> list[ActivityCategory]:
        """Global rows plus the org's customs when org_id is passed."""

    @abstractmethod
    def create(
        self,
        category_id: UUID,
        org_id: UUID | None,
        name: str,
        slug: str,
        description: str | None,
        icon: str | None,
        default_hours: float | None,
        color: str | None,
    ) -> ActivityCategory:
        """Insert one catalog row (global or org-scoped)."""


class OrgTagStore(ABC):
    """Persistence port for the per-org tag catalog and its indexes."""

    @abstractmethod
    def get(self, org_id: UUID, slug: str) -> TagByOrg | None:
        """Load one catalog row inside one org."""

    @abstractmethod
    def list(self, org_id: UUID) -> list[TagByOrg]:
        """Every catalog row of one org, slug order."""

    @abstractmethod
    def claim(
        self,
        org_id: UUID,
        tag_id: UUID,
        slug: str,
        name: str,
        now: datetime,
    ) -> tuple[TagByOrg, bool]:
        """LWT claim on (org_id, slug); losers get (winner, False)."""

    @abstractmethod
    def rename(
        self,
        org_id: UUID,
        row: TagByOrg,
        slug: str,
        name: str,
        now: datetime,
    ) -> TagByOrg | None:
        """Rename a catalog row. A new slug claims (org_id, slug)
        keeping tag_id/created_at and writes its directory row, but
        leaves the old row for the caller to remove after retag so a
        mid-flight failure never loses the catalog entry; None when the
        new slug was claimed concurrently."""

    @abstractmethod
    def remove(self, org_id: UUID, slug: str) -> None:
        """Drop the catalog row, its directory row and any remembered
        trash edges for the slug."""

    @abstractmethod
    def snapshot_trash_edges(self, org_id: UUID, slug: str) -> None:
        """Copy the slug's live edge rows into trashed_tag_edges_by_org
        (upsert, idempotent) before they are stripped."""

    @abstractmethod
    def mark_trashed(
        self, org_id: UUID, slug: str, now: datetime
    ) -> None:
        """Stamp deleted_at on the catalog row and drop its directory
        row so the slug leaves the public surface."""

    @abstractmethod
    def restore_edges(
        self, org_id: UUID, slug: str, name: str, now: datetime
    ) -> tuple[list[UUID], int]:
        """Re-attach the slug to remembered activities that still
        exist: skip ones already carrying it, count ones at the 10-tag
        cap as skipped, otherwise append `name` at the end of
        tag_names, rewrite the live feed row and upsert the edge.
        Remembered rows are kept. Returns (attached_ids, skipped)."""

    @abstractmethod
    def mark_restored(
        self, org_id: UUID, slug: str, name: str, now: datetime
    ) -> None:
        """Clear deleted_at, rewrite the directory row and delete the
        remembered edges for the slug."""

    @abstractmethod
    def trashed_usage(self, org_id: UUID) -> dict[str, int]:
        """Slug -> remembered rows whose activity is not trashed."""

    @abstractmethod
    def retag(
        self,
        org_id: UUID,
        slug: str,
        replacement: str | None,
        now: datetime,
        only: set[UUID] | None = None,
    ) -> list[UUID]:
        """Rewrite tag_names on edged activities: the name whose
        tag_slug() matches `slug` becomes `replacement` in place (None
        drops it), dedupe by slug keeps the first occurrence. Live
        activities also rewrite their activities_by_tag rows; edges
        mirror the result. `only` restricts the write to those
        activity ids; None rewrites every edge (catalog curation).
        Returns the touched activity ids."""

    @abstractmethod
    def usage(self, org_id: UUID) -> dict[str, int]:
        """Slug -> count of edged activities not in the org trash."""

    @abstractmethod
    def directory(self) -> list[PublicTagDirectory]:
        """The whole 'all' partition of the public tag directory."""


class ActivityEvents(ABC):
    """Fan-out port: one live event per committed lifecycle mutation."""

    @abstractmethod
    def activity_changed(
        self,
        org_id: UUID,
        action: str,
        activity_id: UUID,
        actor_id: UUID,
        status: str,
    ) -> None:
        """Publish lifecycle changes onto activities:{org_id}."""

    @abstractmethod
    def tags_changed(
        self, org_id: UUID, action: str, slug: str, actor_id: UUID
    ) -> None:
        """Publish one tag.* refetch hint onto activities:{org_id}."""


class ActivityChatLink(ABC):
    """Chat side of the trash lifecycle (event room + linked threads)."""

    @abstractmethod
    def activity_changed(self, org_id: UUID, activity_id: UUID) -> None:
        """Trash/restore hint so open inboxes refetch the frozen state."""

    @abstractmethod
    def activity_purged(
        self,
        org_id: UUID,
        activity_id: UUID,
        created_at: datetime | None,
        actor_id: UUID,
    ) -> None:
        """Hard delete: wipe the event room, archive linked threads."""
