"""Abstract ports for the profiles bounded context (DIP wiring)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from profiles.model import (
    EmergencyContact,
    Skill,
    StudentProfile,
    UserBySkill,
    UserSkill,
)


class ProfileStore(ABC):
    """Persistence port for student profile, contacts, and skill edges."""

    @abstractmethod
    def get_profile(self, user_id: UUID) -> StudentProfile | None:
        """Load the profile row, or None when the user has none yet."""

    @abstractmethod
    def upsert_profile(
        self,
        user_id: UUID,
        student_code: str | None,
        class_name: str | None,
        enrollment_year: int | None,
        school_name: str | None,
        bio: str | None,
        interests: set[str],
        status: str | None,
        now: datetime,
    ) -> StudentProfile:
        """Create-or-replace the editable profile fields."""

    @abstractmethod
    def list_contacts(self, user_id: UUID) -> list[EmergencyContact]:
        """All emergency contacts for one user, oldest first."""

    @abstractmethod
    def put_contact(
        self,
        user_id: UUID,
        contact_id: UUID,
        name: str,
        relation: str | None,
        phone: str,
        is_primary: bool,
    ) -> EmergencyContact:
        """Insert or overwrite one contact row."""

    @abstractmethod
    def delete_contact(self, user_id: UUID, contact_id: UUID) -> bool:
        """Remove one contact. False when it never existed."""

    @abstractmethod
    def clear_primary_contacts(self, user_id: UUID, keep: UUID | None) -> None:
        """Demote every is_primary flag except the kept contact."""

    @abstractmethod
    def list_skills(self) -> list[Skill]:
        """Full seeded catalog, sorted by name."""

    @abstractmethod
    def get_skill(self, skill_id: UUID) -> Skill | None:
        """One catalog row by primary key."""

    @abstractmethod
    def list_user_skills(self, user_id: UUID) -> list[UserSkill]:
        """All skill edges of one user."""

    @abstractmethod
    def list_users_by_skill(
        self, skill_id: UUID, limit: int = 200
    ) -> list[UserBySkill]:
        """Reverse edge: every user holding one skill (matching feed)."""

    @abstractmethod
    def replace_user_skills(
        self, user_id: UUID, edges: list[tuple[UUID, int]]
    ) -> None:
        """Rewrite both directions: delete removed rows, upsert kept ones."""
