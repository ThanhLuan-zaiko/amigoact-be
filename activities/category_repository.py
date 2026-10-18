"""cqlengine persistence for the activity category catalog."""

from __future__ import annotations

from uuid import UUID

from activities.interfaces import CategoryStore
from activities.model import ActivityCategory


class CqlCategoryStore(CategoryStore):
    """Catalog reads include global rows plus the org's customs."""

    def get(self, category_id: UUID) -> ActivityCategory | None:
        return ActivityCategory.objects(id=category_id).first()

    def list(self, org_id: UUID | None) -> list[ActivityCategory]:
        return sorted(
            (
                row
                for row in ActivityCategory.objects.all()
                if row.org_id is None or row.org_id == org_id
            ),
            key=lambda row: (row.name or "").lower(),
        )

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
        return ActivityCategory.create(
            id=category_id,
            org_id=org_id,
            name=name,
            slug=slug,
            description=description,
            icon=icon,
            default_hours=default_hours,
            color=color,
        )
