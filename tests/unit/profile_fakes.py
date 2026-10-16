"""Shared in-memory ports for ProfileService unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import uuid_utils

from profiles.interfaces import ProfileStore
from profiles.service import ProfileService
from tests.unit.auth_fakes import FakeUsers
from tests.unit.org_fakes import FakeMedia, FakeStore


class FakeProfiles(ProfileStore):
    def __init__(self) -> None:
        self.profiles: dict[UUID, Any] = {}
        self.contacts: dict[UUID, dict[UUID, Any]] = {}
        self.skills: dict[UUID, Any] = {}
        self.user_skills: dict[UUID, dict[UUID, int]] = {}
        self.reverse_skills: dict[UUID, dict[UUID, int]] = {}

    def add_skill(self, name: str, slug: str) -> Any:
        row = SimpleNamespace(id=uuid_utils.uuid7(), name=name, slug=slug)
        self.skills[row.id] = row
        return row

    def get_profile(self, user_id):  # noqa: ANN001, ANN202
        return self.profiles.get(user_id)

    def upsert_profile(self, user_id, student_code, class_name, enrollment_year, school_name, bio, interests, status, now):  # noqa: ANN001, ANN202
        row = self.profiles.get(user_id)
        if row is None:
            row = SimpleNamespace(
                user_id=user_id, total_hours=0.0,
                campus_id=None, department_id=None,
            )
            self.profiles[user_id] = row
        row.student_code = student_code
        row.class_name = class_name
        row.enrollment_year = enrollment_year
        row.school_name = school_name
        row.bio = bio
        row.interests = interests
        row.status = status or "studying"
        row.updated_at = now
        return row

    def list_contacts(self, user_id):  # noqa: ANN001, ANN202
        return list(self.contacts.get(user_id, {}).values())

    def put_contact(self, user_id, contact_id, name, relation, phone, is_primary):  # noqa: ANN001, ANN202
        row = SimpleNamespace(
            user_id=user_id, contact_id=contact_id, name=name,
            relation=relation, phone=phone, is_primary=is_primary,
        )
        self.contacts.setdefault(user_id, {})[contact_id] = row
        return row

    def delete_contact(self, user_id, contact_id):  # noqa: ANN001, ANN202
        return (
            self.contacts.get(user_id, {}).pop(contact_id, None) is not None
        )

    def clear_primary_contacts(self, user_id, keep):  # noqa: ANN001, ANN202
        for row in self.contacts.get(user_id, {}).values():
            if row.contact_id != keep:
                row.is_primary = False

    def list_skills(self):  # noqa: ANN001, ANN202
        return sorted(self.skills.values(), key=lambda s: s.name.lower())

    def get_skill(self, skill_id):  # noqa: ANN001, ANN202
        return self.skills.get(skill_id)

    def list_user_skills(self, user_id):  # noqa: ANN001, ANN202
        return [
            SimpleNamespace(user_id=user_id, skill_id=sid, level=level)
            for sid, level in self.user_skills.get(user_id, {}).items()
        ]

    def list_users_by_skill(self, skill_id, limit=200):  # noqa: ANN001, ANN202
        return [
            SimpleNamespace(skill_id=skill_id, user_id=uid, level=level)
            for uid, level in self.reverse_skills.get(skill_id, {}).items()
        ][:limit]

    def replace_user_skills(self, user_id, edges):  # noqa: ANN001, ANN202
        keep = {sid for sid, _ in edges}
        for sid in list(self.user_skills.get(user_id, {})):
            if sid not in keep:
                del self.user_skills[user_id][sid]
                self.reverse_skills.get(sid, {}).pop(user_id, None)
        for sid, level in edges:
            self.user_skills.setdefault(user_id, {})[sid] = level
            self.reverse_skills.setdefault(sid, {})[user_id] = level


def make_service() -> tuple[
    ProfileService, FakeProfiles, FakeUsers, FakeMedia
]:
    profiles, users, media = FakeProfiles(), FakeUsers(), FakeMedia()
    return (
        ProfileService(
            profiles=profiles,
            users=users,
            media=media,
            store=FakeStore(),
        ),
        profiles,
        users,
        media,
    )


def new_user(users: FakeUsers, **overrides: Any) -> Any:
    """Register a fake user row with sane defaults."""
    from datetime import UTC, datetime

    uid = uuid_utils.uuid7()
    user = users.create(
        uid,
        f"{uid.hex[:8]}@test.dev",
        "0901234567",
        "hash",
        "Volunteer One",
        datetime.now(UTC),
    )
    for key, value in overrides.items():
        setattr(user, key, value)
    return user
