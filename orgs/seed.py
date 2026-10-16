"""Idempotent org-types seeding -- the runtime org-kind catalog."""

from __future__ import annotations

from orgs.model import OrgType

_TYPES: tuple[tuple[str, str, int], ...] = (
    ("organization", "T\u1ed5 ch\u1ee9c", 0),
    ("club", "C\xe2u l\u1ea1c b\u1ed9", 1),
    ("group", "Nh\xf3m", 2),
    ("business", "Doanh nghi\u1ec7p", 3),
)


def seed_org_types() -> int:
    """Upsert the canonical kinds; returns rows written."""
    written = 0
    for code, name, sort_order in _TYPES:
        OrgType.create(code=code, name=name, sort_order=sort_order)
        written += 1
    return written
