"""Abstract ports for the activities bounded context (DIP wiring)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from activities.model import (
    ActivitiesBySlug,
    Activity,
    ActivityAnnouncement,
    ActivityCategory,
    ActivityPartner,
    ActivitySchedule,
    ActivitySkill,
    ActivityStaff,
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


class ActivityLinkStore(ABC):
    """Persistence port for skill and partner edges of one activity."""

    @abstractmethod
    def set_skills(
        self, activity_id: UUID, edges: list[tuple[UUID, bool]]
    ) -> None:
        """Replace all skill edges (skill_id, is_required pairs)."""

    @abstractmethod
    def list_skills(self, activity_id: UUID) -> list[ActivitySkill]:
        """Skill edges of one activity."""

    @abstractmethod
    def set_partners(
        self,
        activity: Activity,
        edges: list[tuple[UUID, str, str | None]],
    ) -> None:
        """Replace partner edges plus the per-org reverse feed."""

    @abstractmethod
    def list_partners(self, activity_id: UUID) -> list[ActivityPartner]:
        """Partner edges of one activity."""

    @abstractmethod
    def list_partner_feed(
        self, org_id: UUID, limit: int = 50
    ) -> list[Activity]:
        """Activities one org partners on, newest first."""


class ActivityStaffStore(ABC):
    """Persistence port for staff assignments."""

    @abstractmethod
    def set_staff(
        self,
        activity_id: UUID,
        rows: list[tuple[UUID, str]],
        assigned_by: UUID,
        now: datetime,
    ) -> None:
        """Replace all assignments (user_id, staff_role pairs)."""

    @abstractmethod
    def list_staff(self, activity_id: UUID) -> list[ActivityStaff]:
        """Staff rows of one activity."""


class ScheduleStore(ABC):
    """Persistence port for activity schedules (sessions)."""

    @abstractmethod
    def create(
        self,
        schedule_id: UUID,
        activity_id: UUID,
        title: str,
        location: str | None,
        start_at: datetime | None,
        end_at: datetime | None,
        now: datetime,
    ) -> ActivitySchedule:
        """Insert one schedule row."""

    @abstractmethod
    def list(self, activity_id: UUID) -> list[ActivitySchedule]:
        """All schedules of one activity."""

    @abstractmethod
    def delete(self, activity_id: UUID, schedule_id: UUID) -> bool:
        """Remove one schedule. False when it never existed."""


class AnnouncementStore(ABC):
    """Persistence port for the activity news board."""

    @abstractmethod
    def create(
        self,
        activity_id: UUID,
        announcement_id: UUID,
        title: str,
        body: str,
        created_by: UUID,
        now: datetime,
    ) -> ActivityAnnouncement:
        """Append one announcement."""

    @abstractmethod
    def list(
        self, activity_id: UUID, limit: int = 50
    ) -> list[ActivityAnnouncement]:
        """Newest-first announcements of one activity."""


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
