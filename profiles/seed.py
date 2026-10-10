"""Idempotent skill-catalog seeding.

Fixed UUIDs keep the catalog stable across resets so tests and seeds can
reference a skill by id. Slugs are the public identifier users see.
"""

from __future__ import annotations

from uuid import UUID

from profiles.model import Skill, SkillBySlug

_CATALOG: tuple[tuple[str, str, str], ...] = (
    ("first-aid", "First Aid", "0197f6a1-0001-7000-8000-000000000001"),
    ("teaching", "Teaching & Tutoring", "0197f6a1-0001-7000-8000-000000000002"),
    ("translation", "Translation", "0197f6a1-0001-7000-8000-000000000003"),
    ("logistics", "Logistics", "0197f6a1-0001-7000-8000-000000000004"),
    ("photography", "Photography", "0197f6a1-0001-7000-8000-000000000005"),
    ("videography", "Videography", "0197f6a1-0001-7000-8000-000000000006"),
    ("it-support", "IT Support", "0197f6a1-0001-7000-8000-000000000007"),
    ("cooking", "Cooking & Catering", "0197f6a1-0001-7000-8000-000000000008"),
    ("driving", "Driving", "0197f6a1-0001-7000-8000-000000000009"),
    ("healthcare", "Healthcare", "0197f6a1-0001-7000-8000-00000000000a"),
    ("event-staff", "Event Staffing", "0197f6a1-0001-7000-8000-00000000000b"),
    ("fundraising", "Fundraising", "0197f6a1-0001-7000-8000-00000000000c"),
    ("environment", "Environmental Care", "0197f6a1-0001-7000-8000-00000000000d"),
    ("sports", "Sports & Coaching", "0197f6a1-0001-7000-8000-00000000000e"),
    ("music", "Music & Performance", "0197f6a1-0001-7000-8000-00000000000f"),
    ("social-media", "Social Media", "0197f6a1-0001-7000-8000-000000000010"),
    ("design", "Graphic Design", "0197f6a1-0001-7000-8000-000000000011"),
    ("counseling", "Counseling", "0197f6a1-0001-7000-8000-000000000012"),
)


def seed_skills() -> None:
    """Insert missing catalog rows; safe to run on every boot."""
    for slug, name, skill_id in _CATALOG:
        if SkillBySlug.objects(slug=slug).first() is None:
            SkillBySlug.create(slug=slug, skill_id=UUID(skill_id))
        if Skill.objects(id=UUID(skill_id)).first() is None:
            Skill.create(id=UUID(skill_id), name=name, slug=slug)
