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
    TagBySlug,
)


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


class TagStore(ABC):
    """Persistence port for the global tag catalog (tags_by_slug)."""

    @abstractmethod
    def get_by_slug(self, slug: str) -> TagBySlug | None:
        """Load one catalog row by its canonical slug."""

    @abstractmethod
    def claim(
        self, tag_id: UUID, slug: str, name: str, now: datetime
    ) -> TagBySlug:
        """LWT-insert the slug; returns the winner on a lost race."""

    @abstractmethod
    def search(self, query: str, limit: int = 20) -> list[TagBySlug]:
        """Folded-substring search across the whole catalog."""


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
