"""Volunteer-profile business rules: profile, skills, contacts, avatar."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from auth.interfaces import UserRepository
from core.exceptions import (
    InvalidSkillLevelError,
    MediaTooLargeError,
    NotFoundError,
    SkillNotFoundError,
    TooManyContactsError,
    UnsupportedMediaError,
)
from core.media import MediaStore, media_kind, normalize_image
from core.security import utcnow
from profiles.interfaces import ProfileStore
from profiles.model import EmergencyContact, Skill, StudentProfile
from orgs.interfaces import MediaRepository

_MAX_CONTACTS = 3
_SKILL_MIN, _SKILL_MAX = 1, 5


@dataclass(frozen=True)
class SkillEdge:
    """One user-skill edge joined with its catalog row."""

    skill_id: UUID
    name: str
    slug: str
    level: int


@dataclass(frozen=True)
class ProfileBundle:
    """Everything the /profiles/me surface renders in one shot."""

    profile: StudentProfile | None
    skills: list[SkillEdge]
    contacts: list[EmergencyContact]
    avatar_url: str | None


@dataclass(frozen=True)
class PublicCard:
    """Volunteer card for public pages; strips private contact rows."""

    full_name: str
    member_since: datetime | None
    profile: StudentProfile | None
    skills: list[SkillEdge]
    avatar_url: str | None


class ProfileService:
    """Own-profile reads/writes plus the public volunteer card."""

    def __init__(
        self,
        profiles: ProfileStore,
        users: UserRepository,
        media: MediaRepository,
        store: MediaStore,
        max_image_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        self._profiles = profiles
        self._users = users
        self._media = media
        self._store = store
        self._max_image_bytes = max_image_bytes

    def _skill_edges(self, user_id: UUID) -> list[SkillEdge]:
        """Join user_skills rows with the catalog for names."""
        edges: list[SkillEdge] = []
        for row in self._profiles.list_user_skills(user_id):
            skill = self._profiles.get_skill(row.skill_id)
            if skill is None:
                continue
            edges.append(
                SkillEdge(
                    skill_id=row.skill_id,
                    name=skill.name,
                    slug=skill.slug,
                    level=int(row.level or 1),
                )
            )
        return sorted(edges, key=lambda e: e.name.lower())

    def _avatar_url(self, user_id: UUID) -> str | None:
        user = self._users.get_by_id(user_id)
        asset_id = getattr(user, "avatar_media_id", None) if user else None
        if asset_id is None:
            return None
        row = self._media.get_asset(asset_id)
        return f"/media/{row.file_url}" if row else None

    def get_mine(self, user_id: UUID) -> ProfileBundle:
        """Full bundle for the profile dashboard card."""
        return ProfileBundle(
            profile=self._profiles.get_profile(user_id),
            skills=self._skill_edges(user_id),
            contacts=self._profiles.list_contacts(user_id),
            avatar_url=self._avatar_url(user_id),
        )

    def update_mine(
        self,
        user_id: UUID,
        *,
        student_code: str | None,
        class_name: str | None,
        enrollment_year: int | None,
        school_name: str | None,
        bio: str | None,
        interests: set[str],
        status: str | None,
        campus_id: UUID | None = None,
        department_id: UUID | None = None,
    ) -> ProfileBundle:
        """Create-or-replace editable fields; total_hours is ledger-owned."""
        self._profiles.upsert_profile(
            user_id,
            student_code,
            campus_id,
            department_id,
            class_name,
            enrollment_year,
            school_name,
            bio,
            interests,
            status,
            utcnow(),
        )
        return self.get_mine(user_id)

    def list_catalog(self) -> list[Skill]:
        """Sorted skill catalog for pickers."""
        return self._profiles.list_skills()

    def set_skills(
        self, user_id: UUID, edges: list[tuple[UUID, int]]
    ) -> ProfileBundle:
        """Replace the whole skill set after validating every edge."""
        merged: dict[UUID, int] = {}
        for skill_id, level in edges:
            if not (_SKILL_MIN <= level <= _SKILL_MAX):
                raise InvalidSkillLevelError(
                    "Skill level must be between 1 and 5."
                )
            if self._profiles.get_skill(skill_id) is None:
                raise SkillNotFoundError("Skill does not exist.")
            merged[skill_id] = level
        self._profiles.replace_user_skills(user_id, list(merged.items()))
        return self.get_mine(user_id)

    def add_contact(
        self,
        user_id: UUID,
        *,
        name: str,
        relation: str | None,
        phone: str,
        is_primary: bool,
    ) -> ProfileBundle:
        """Append one emergency contact, capped at _MAX_CONTACTS."""
        contacts = self._profiles.list_contacts(user_id)
        if len(contacts) >= _MAX_CONTACTS:
            raise TooManyContactsError(
                f"At most {_MAX_CONTACTS} emergency contacts are allowed."
            )
        from core.ids import uuid7

        contact_id = uuid7()
        if is_primary or not contacts:
            self._profiles.clear_primary_contacts(user_id, keep=None)
            is_primary = True
        self._profiles.put_contact(
            user_id, contact_id, name, relation, phone, is_primary
        )
        return self.get_mine(user_id)

    def remove_contact(self, user_id: UUID, contact_id: UUID) -> ProfileBundle:
        """Delete one contact; the newest survivor becomes primary."""
        if not self._profiles.delete_contact(user_id, contact_id):
            raise NotFoundError("Emergency contact not found.")
        survivors = self._profiles.list_contacts(user_id)
        if survivors and not any(c.is_primary for c in survivors):
            survivor = survivors[-1]
            self._profiles.put_contact(
                user_id,
                survivor.contact_id,
                survivor.name,
                survivor.relation,
                survivor.phone,
                True,
            )
        return self.get_mine(user_id)

    def upload_avatar(
        self, user_id: UUID, filename: str, mime: str, content: bytes
    ) -> str:
        """Store one image under users/<id>/ and point avatar_media_id at it."""
        if media_kind(mime) != "image":
            raise UnsupportedMediaError("Avatar must be an image.")
        if len(content) > self._max_image_bytes:
            raise MediaTooLargeError("File exceeds the size limit.")
        try:
            mime, content = normalize_image(content, mime)
        except ValueError as exc:
            raise MediaTooLargeError(
                "Image exceeds the pixel limit."
            ) from exc
        from core.ids import uuid7

        asset_id = uuid7()
        relative = self._store.save_user_media(
            user_id, asset_id, mime, filename, content
        )
        old_asset_id = getattr(
            self._users.get_by_id(user_id), "avatar_media_id", None
        )
        now = utcnow()
        self._media.create_asset(
            asset_id,
            user_id,
            relative,
            mime,
            len(content),
            now,
            "avatar",
            file_hash=hashlib.sha256(content).hexdigest(),
            uploader_id=user_id,
            original_name=filename,
        )
        self._users.set_avatar_media(user_id, asset_id, now)
        if old_asset_id is not None and old_asset_id != asset_id:
            old = self._media.get_asset(old_asset_id)
            if old is not None:
                self._media.delete_asset(old_asset_id)
                self._store.delete_file(old.file_url)
        return f"/media/{relative}"

    def public_card(self, user_id: UUID) -> PublicCard:
        """Volunteer card for public pages; 404 without an active user."""
        user = self._users.get_by_id(user_id)
        if user is None or getattr(user, "status", "active") != "active":
            raise NotFoundError("Volunteer not found.")
        return PublicCard(
            full_name=getattr(user, "full_name", "") or "Volunteer",
            member_since=getattr(user, "created_at", None),
            profile=self._profiles.get_profile(user_id),
            skills=self._skill_edges(user_id),
            avatar_url=self._avatar_url(user_id),
        )
