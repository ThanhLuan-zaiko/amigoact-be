"""Idempotent global activity-category seeding.

Fixed UUIDs keep the catalog stable across resets; orgs can still add
their own scoped categories through the API.
"""

from __future__ import annotations

from uuid import UUID

from activities.model import ActivityCategory

_GLOBAL: tuple[tuple[str, str, str, float | None], ...] = (
    ("environment", "M\u00f4i tr\u01b0\u1eddng", "0197f6a2-0001-7000-8000-000000000001", 4.0),
    ("education", "Gi\u00e1o d\u1ee5c", "0197f6a2-0001-7000-8000-000000000002", 4.0),
    ("health", "Y t\u1ebf & S\u1ee9c kh\u1ecfe", "0197f6a2-0001-7000-8000-000000000003", 6.0),
    ("community", "C\u1ed9ng \u0111\u1ed3ng", "0197f6a2-0001-7000-8000-000000000004", 4.0),
    ("disaster", "C\u1ee9u tr\u1ee3 thi\u00ean tai", "0197f6a2-0001-7000-8000-000000000005", 8.0),
    ("fundraising", "G\u00e2y qu\u1ef9", "0197f6a2-0001-7000-8000-000000000006", 3.0),
    ("events", "S\u1ef1 ki\u1ec7n", "0197f6a2-0001-7000-8000-000000000007", 4.0),
    ("other", "Kh\u00e1c", "0197f6a2-0001-7000-8000-000000000008", None),
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
