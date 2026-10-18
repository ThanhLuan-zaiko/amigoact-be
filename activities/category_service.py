"""Category catalog rules: global rows plus member-visible org customs."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from activities.interfaces import CategoryStore
from activities.model import ActivityCategory
from core.exceptions import ForbiddenError, NotFoundError
from core.ids import uuid7
from orgs.interfaces import OrgRepository
from rbac.interfaces import AccessControl


@dataclass(frozen=True)
class CategorySnapshot:
    """Flat category row for pickers."""

    id: UUID
    name: str
    slug: str
    org_scoped: bool
    default_hours: float | None


class CategoryService:
    """Catalog reads for everyone; org customs need manager rights."""

    def __init__(
        self,
        categories: CategoryStore,
        orgs: OrgRepository,
        access: AccessControl,
    ) -> None:
        self._categories = categories
        self._orgs = orgs
        self._access = access

    def _is_member(self, org_id: UUID, user_id: UUID | None) -> bool:
        return user_id is not None and self._orgs.is_member(
            org_id, user_id
        )

    def list_categories(
        self, org_id: UUID | None, viewer_id: UUID | None
    ) -> list[CategorySnapshot]:
        """Global catalog for anyone; org customs need membership."""
        scope = None
        if org_id is not None and self._is_member(org_id, viewer_id):
            scope = org_id
        return [self._category(c) for c in self._categories.list(scope)]

    def create_category(
        self,
        org_id: UUID,
        actor_id: UUID,
        name: str,
        slug: str,
        description: str | None,
        icon: str | None,
        default_hours: float | None,
        color: str | None,
    ) -> CategorySnapshot:
        """Managers extend the catalog with org-scoped categories."""
        org = self._orgs.get_by_id(org_id)
        if org is None or getattr(org, "deleted_at", None) is not None:
            raise NotFoundError("Organization not found.")
        if getattr(org, "owner_id", None) != actor_id and not (
            self._access.has_permission(
                org_id, actor_id, "activity:manage"
            )
        ):
            raise ForbiddenError("Only org managers can do this.")
        row = self._categories.create(
            uuid7(),
            org_id,
            name,
            slug,
            description,
            icon,
            default_hours,
            color,
        )
        return self._category(row)

    @staticmethod
    def _category(row: ActivityCategory) -> CategorySnapshot:
        return CategorySnapshot(
            id=row.id,
            name=row.name,
            slug=row.slug,
            org_scoped=row.org_id is not None,
            default_hours=row.default_hours,
        )
