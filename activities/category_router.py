"""HTTP layer for the activity category catalog."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from activities.schemas import CategoryCreate, CategoryItem
from core.dependencies import (
    CurrentUser,
    get_current_user,
    get_optional_user,
)
from core.dependencies_features import get_category_service

if TYPE_CHECKING:
    from activities.category_service import CategoryService

router = APIRouter(tags=["activities"])


@router.get("/categories", response_model=list[CategoryItem])
def list_categories(
    org_id: UUID | None = Query(default=None),
    viewer: CurrentUser | None = Depends(get_optional_user),
    service: CategoryService = Depends(get_category_service),
) -> list[CategoryItem]:
    """Global catalog plus the member's org customs."""
    return [
        CategoryItem(
            id=row.id,
            name=row.name,
            slug=row.slug,
            org_scoped=row.org_scoped,
            default_hours=row.default_hours,
        )
        for row in service.list_categories(
            org_id, viewer.id if viewer else None
        )
    ]


@router.post(
    "/orgs/{org_id}/categories",
    response_model=CategoryItem,
    status_code=201,
)
def create_category(
    org_id: UUID,
    body: CategoryCreate,
    current: CurrentUser = Depends(get_current_user),
    service: CategoryService = Depends(get_category_service),
) -> CategoryItem:
    """Managers add an org-scoped category to the catalog."""
    row = service.create_category(
        org_id,
        current.id,
        body.name,
        body.slug,
        body.description,
        body.icon,
        body.default_hours,
        body.color,
    )
    return CategoryItem(
        id=row.id,
        name=row.name,
        slug=row.slug,
        org_scoped=row.org_scoped,
        default_hours=row.default_hours,
    )
