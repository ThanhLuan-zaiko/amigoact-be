"""HTTP layer for the public tag directory and org tag curation."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response

from activities.tag_schemas import (
    TAG_SLUG,
    OrgTagItem,
    OrgTagPage,
    PublicTagItem,
    TagMergeBody,
    TagNameBody,
)
from core.dependencies import CurrentUser, get_current_user
from core.dependencies_tags import get_tag_admin_service, get_tag_service

if TYPE_CHECKING:
    from activities.tag_admin_service import (
        OrgTagSnapshot,
        TagAdminService,
    )
    from activities.tag_service import TagService

router = APIRouter(tags=["tags"])


def _item(row: OrgTagSnapshot) -> OrgTagItem:
    return OrgTagItem(
        id=row.id,
        name=row.name,
        slug=row.slug,
        activity_count=row.activity_count,
        created_at=row.created_at,
        deleted_at=row.deleted_at,
    )


@router.get("/tags", response_model=list[PublicTagItem])
def search_tags(
    q: str = Query(default="", max_length=60),
    limit: int = Query(default=20, ge=1, le=100),
    service: TagService = Depends(get_tag_service),
) -> list[PublicTagItem]:
    """Cross-org typeahead suggestions grouped by slug."""
    return [
        PublicTagItem(name=row.name, slug=row.slug)
        for row in service.search_public(q, limit)
    ]


@router.get("/orgs/{org_id}/tags", response_model=OrgTagPage)
def list_org_tags(
    org_id: UUID,
    q: str = Query(default="", max_length=60),
    limit: int = Query(default=500, ge=1, le=1000),
    trash: bool = Query(default=False),
    current: CurrentUser = Depends(get_current_user),
    service: TagAdminService = Depends(get_tag_admin_service),
) -> OrgTagPage:
    """Member-readable catalog page; `?trash=1` is manager-only."""
    page = service.list_tags(org_id, current.id, q, limit, trash)
    return OrgTagPage(
        items=[_item(row) for row in page.items],
        can_manage=page.can_manage,
        trash_count=page.trash_count,
    )


@router.post(
    "/orgs/{org_id}/tags", response_model=OrgTagItem, status_code=201
)
def create_org_tag(
    org_id: UUID,
    body: TagNameBody,
    current: CurrentUser = Depends(get_current_user),
    service: TagAdminService = Depends(get_tag_admin_service),
) -> OrgTagItem:
    """tag:manage holders add a catalog entry directly."""
    return _item(service.create_tag(org_id, current.id, body.name))


@router.patch(
    "/orgs/{org_id}/tags/{slug}", response_model=OrgTagItem
)
def rename_org_tag(
    org_id: UUID,
    body: TagNameBody,
    slug: str = Path(pattern=TAG_SLUG),
    current: CurrentUser = Depends(get_current_user),
    service: TagAdminService = Depends(get_tag_admin_service),
) -> OrgTagItem:
    """Rename a catalog row and retag every activity using it."""
    return _item(service.rename_tag(org_id, current.id, slug, body.name))


@router.post(
    "/orgs/{org_id}/tags/{slug}/merge", response_model=OrgTagItem
)
def merge_org_tag(
    org_id: UUID,
    body: TagMergeBody,
    slug: str = Path(pattern=TAG_SLUG),
    current: CurrentUser = Depends(get_current_user),
    service: TagAdminService = Depends(get_tag_admin_service),
) -> OrgTagItem:
    """Fold the slug into the target; returns the surviving tag."""
    return _item(service.merge_tags(org_id, current.id, slug, body.into))


@router.post(
    "/orgs/{org_id}/tags/{slug}/restore", response_model=OrgTagItem
)
def restore_org_tag(
    org_id: UUID,
    slug: str = Path(pattern=TAG_SLUG),
    current: CurrentUser = Depends(get_current_user),
    service: TagAdminService = Depends(get_tag_admin_service),
) -> OrgTagItem:
    """Bring a trashed tag back and re-attach its remembered activities."""
    return _item(service.restore_tag(org_id, current.id, slug))


@router.delete("/orgs/{org_id}/tags/{slug}", response_model=OrgTagItem)
def delete_org_tag(
    org_id: UUID,
    hard: bool = Query(default=False),
    slug: str = Path(pattern=TAG_SLUG),
    current: CurrentUser = Depends(get_current_user),
    service: TagAdminService = Depends(get_tag_admin_service),
) -> OrgTagItem | Response:
    """Soft delete detaches the tag into the org trash; `?hard=1`
    purges it permanently with an empty 204 body."""
    if hard:
        service.erase_tag(org_id, current.id, slug)
        return Response(status_code=204)
    return _item(service.trash_tag(org_id, current.id, slug))
