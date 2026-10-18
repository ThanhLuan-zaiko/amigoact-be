"""Abstract ports for the activity detail aggregate (edge tables).

Split from interfaces.py for the 350-line rule: these stores back
detail_service.py, links_repository.py, ops_repository.py,
form_service.py, slot_service.py and the media gallery.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from activities.model import (
    Activity,
    ActivityAnnouncement,
    ActivityMedia,
    ActivityPartner,
    ActivitySchedule,
    ActivitySkill,
    ActivitySlot,
    ActivityStaff,
    RegistrationForm,
)


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


class RegistrationFormStore(ABC):
    """Persistence port for per-activity sign-up form questions."""

    @abstractmethod
    def list_form(self, activity_id: UUID) -> list[RegistrationForm]:
        """Questions in display order."""

    @abstractmethod
    def replace_form(
        self,
        activity_id: UUID,
        questions: list[tuple[UUID, str, str, bool]],
    ) -> None:
        """Rewrite the form; each tuple is
        (question_id, label, field_type, required) at list position."""


class SlotStore(ABC):
    """Persistence port for per-schedule capacity slots."""

    @abstractmethod
    def list(self, schedule_id: UUID) -> list[ActivitySlot]:
        """All slots of one schedule."""

    @abstractmethod
    def list_for_activity(self, activity_id: UUID) -> list[ActivitySlot]:
        """All slots across the activity's schedules."""

    @abstractmethod
    def create(
        self,
        slot_id: UUID,
        schedule_id: UUID,
        title: str,
        capacity: int | None,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> ActivitySlot:
        """Insert one slot."""

    @abstractmethod
    def delete(self, schedule_id: UUID, slot_id: UUID) -> bool:
        """Remove one slot. False when it never existed."""


class ActivityMediaStore(ABC):
    """Persistence port for the ordered activity_media gallery."""

    @abstractmethod
    def list_for_activity(self, activity_id: UUID) -> list[ActivityMedia]:
        """All entries ordered by position."""

    @abstractmethod
    def create(
        self,
        activity_id: UUID,
        position: int,
        asset_id: UUID,
        role: str,
        caption: str | None,
    ) -> ActivityMedia:
        """Insert one gallery entry."""

    @abstractmethod
    def update(
        self,
        activity_id: UUID,
        position: int,
        asset_id: UUID,
        caption: str | None,
        role: str,
    ) -> None:
        """Replace caption/role of one entry."""

    @abstractmethod
    def delete(self, activity_id: UUID, position: int, asset_id: UUID) -> None:
        """Remove one gallery entry."""
