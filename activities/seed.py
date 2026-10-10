"""Idempotent global activity-category seeding.

Fixed UUIDs keep the catalog stable across resets; orgs can still add
their own scoped categories through the API.
"""

from __future__ import annotations

from uuid import UUID

from activities.model import ActivityCategory

_GLOBAL: tuple[tuple[str, str, str, float | None], ...] = (
    ("environment", "Môi trường", "0197f6a2-0001-7000-8000-000000000001", 4.0),
    ("education", "Giáo dục", "0197f6a2-0001-7000-8000-000000000002", 4.0),
    ("health", "Y tế & Sức khỏe", "0197f6a2-0001-7000-8000-000000000003", 6.0),
    ("community", "Cộng đồng", "0197f6a2-0001-7000-8000-000000000004", 4.0),
    ("disaster", "Cứu trợ thiên tai", "0197f6a2-0001-7000-8000-000000000005", 8.0),
    ("fundraising", "Gây quỹ", "0197f6a2-0001-7000-8000-000000000006", 3.0),
    ("events", "Sự kiện", "0197f6a2-0001-7000-8000-000000000007", 4.0),
    ("other", "Khác", "0197f6a2-0001-7000-8000-000000000008", None),
)


def seed_categories() -> None:
    """Insert missing global rows; safe to run on every boot."""
    for slug, name, category_id, hours in _GLOBAL:
        if ActivityCategory.objects(id=UUID(category_id)).first() is None:
            ActivityCategory.create(
                id=UUID(category_id),
                org_id=None,
                name=name,
                slug=slug,
                description=None,
                icon=None,
                default_hours=hours,
                color=None,
            )
