"""cqlengine models for the volunteer-profiles bounded context."""

from __future__ import annotations

import core.database  # noqa: F401  (reactor compat shim must run first)
from core.ids import uuid7
from cassandra.cqlengine import columns, models


class StudentProfile(models.Model):
    """One row per user; the main profile aggregate."""

    __table_name__ = "student_profiles"
    __keyspace__ = "amigoact"

    user_id = columns.UUID(primary_key=True)
    student_code = columns.Text(required=False)
    campus_id = columns.UUID(required=False)
    department_id = columns.UUID(required=False)
    class_name = columns.Text(required=False)
    enrollment_year = columns.Integer(required=False)
    school_name = columns.Text(required=False)
    bio = columns.Text(required=False)
    interests = columns.Set(columns.Text)
    status = columns.Text(required=False, default="studying")
    total_hours = columns.Double(required=False, default=0.0)
    updated_at = columns.DateTime(required=True)


class EmergencyContact(models.Model):
    """Per-user contact list; contact_id is the clustering key."""

    __table_name__ = "emergency_contacts"
    __keyspace__ = "amigoact"

    user_id = columns.UUID(primary_key=True, partition_key=True)
    contact_id = columns.UUID(
        primary_key=True, clustering_order="ASC", default=uuid7
    )
    name = columns.Text(required=True)
    relation = columns.Text(required=False)
    phone = columns.Text(required=True)
    is_primary = columns.Boolean(required=False, default=False)


class Skill(models.Model):
    """Seeded skill catalog row (first-aid, teaching, translation, ...)."""

    __table_name__ = "skills"
    __keyspace__ = "amigoact"

    id = columns.UUID(primary_key=True, default=uuid7)
    name = columns.Text(required=True)
    slug = columns.Text(required=True)


class SkillBySlug(models.Model):
    """Slug -> skill_id lookup for stable URL/identifier reads."""

    __table_name__ = "skills_by_slug"
    __keyspace__ = "amigoact"

    slug = columns.Text(primary_key=True)
    skill_id = columns.UUID(required=True)


class UserSkill(models.Model):
    """User -> skill edge with a self-declared 1-5 level."""

    __table_name__ = "user_skills"
    __keyspace__ = "amigoact"

    user_id = columns.UUID(primary_key=True, partition_key=True)
    skill_id = columns.UUID(primary_key=True, clustering_order="ASC")
    level = columns.Integer(required=True, default=1)


class UserBySkill(models.Model):
    """Reverse edge: who holds a skill — coordinator matching feed."""

    __table_name__ = "users_by_skill"
    __keyspace__ = "amigoact"

    skill_id = columns.UUID(primary_key=True, partition_key=True)
    user_id = columns.UUID(primary_key=True, clustering_order="ASC")
    level = columns.Integer(required=True, default=1)
