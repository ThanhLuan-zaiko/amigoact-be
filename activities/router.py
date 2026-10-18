"""HTTP layer for activity lifecycle and discovery surfaces."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel

from activities.model import tag_slug
from activities.schemas import (
    ActivityBody,
    ActivityResponse,
    ActivitySummary,
    DiscoveryBucket,
    DiscoveryResponse,
    TagItem,
    TagRef,
    slugify,
)
from core.dependencies import (
    CurrentUser,
    get_current_user,
    get_optional_user,
)
from core.dependencies_features import (
    get_activity_delete_service,
    get_activity_service,
    get_tag_service,
)

if TYPE_CHECKING:
    from activities.delete_service import ActivityDeleteService
    from activities.interfaces import ActivityFields
    from activities.model import Activity
    from activities.service import ActivityService
    from activities.tag_service import TagService

router = APIRouter(tags=["activities"])


class StatusBody(BaseModel):
    """Lifecycle transition request: publish | ongoing | cancel | complete."""

    status: str


def _fields(body: ActivityBody, *, keep_slug: bool) -> ActivityFields:
    """Flatten the request DTO into the service's field bag."""
    from activities.interfaces import ActivityFields as Fields

    slug = body.slug or (None if keep_slug else slugify(body.title))
    return Fields(
        title=body.title,
        slug=slug,
        description=body.description,
        category_id=body.category_id,
        location=body.location,
        address=body.address,
        city=body.city,
        latitude=body.latitude,
        longitude=body.longitude,
        is_remote=body.is_remote,
        max_participants=body.max_participants,
        start_at=body.start_at,
        end_at=body.end_at,
        hours_awarded=body.hours_awarded,
        requirements_json=None,
        registration_deadline=body.registration_deadline,
        person_in_charge_id=body.person_in_charge_id,
        tag_names=body.tags,
    )


def _tags(row: Activity) -> list[TagRef]:
    """Stored canonical names plus their deterministic slugs."""
    return [
        TagRef(name=name, slug=tag_slug(name))
        for name in row.tag_names or []
    ]


def _response(row: Activity) -> ActivityResponse:
    return ActivityResponse(
        id=row.id,
        org_id=row.org_id,
        title=row.title,
        slug=row.slug,
        description=row.description or "",
        category_id=row.category_id,
        status=row.status,
        tags=_tags(row),
        location=row.location,
        address=row.address,
        city=row.city,
        latitude=row.latitude,
        longitude=row.longitude,
        is_remote=bool(row.is_remote),
        max_participants=row.max_participants,
        start_at=row.start_at,
        end_at=row.end_at,
        hours_awarded=float(row.hours_awarded or 0.0),
        registration_deadline=row.registration_deadline,
        person_in_charge_id=row.person_in_charge_id,
        published_at=row.published_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        deleted_at=row.deleted_at,
    )


def _summary(row: Activity) -> ActivitySummary:
    return ActivitySummary(
        id=row.id,
        org_id=row.org_id,
        title=row.title,
        slug=row.slug,
        status=row.status,
        start_at=row.start_at,
        category_id=row.category_id,
        tags=_tags(row),
        deleted_at=row.deleted_at,
    )


@router.get("/activities", response_model=list[ActivitySummary])
def discovery_feed(
    status: str = Query(default="published"),
    category_id: UUID | None = Query(default=None),
    tag: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=50, ge=1, le=100),
    service: ActivityService = Depends(get_activity_service),
) -> list[ActivitySummary]:
    """Public discovery feed; newest-first published activities."""
    return [
        _summary(row)
        for row in service.list_public(
            status, category_id, limit, tag_slug=tag
        )
    ]


@router.get("/tags", response_model=list[TagItem])
def search_tags(
    q: str = Query(default="", max_length=60),
    limit: int = Query(default=20, ge=1, le=100),
    service: TagService = Depends(get_tag_service),
) -> list[TagItem]:
    """Global folksonomy catalog for typeahead pickers."""
    return [
        TagItem(id=row.id, name=row.name, slug=row.slug)
        for row in service.search(q, limit)
    ]


@router.get(
    "/activities/discovery", response_model=DiscoveryResponse
)
def discovery(
    limit: int = Query(default=6, ge=1, le=12),
    service: ActivityService = Depends(get_activity_service),
) -> DiscoveryResponse:
    """Curated shelves for the public discovery page."""
    view = service.discovery(limit)
    return DiscoveryResponse(
        featured=[_summary(row) for row in view.featured],
        upcoming=[_summary(row) for row in view.upcoming],
        categories=[
            DiscoveryBucket(
                category_id=bucket.id,
                name=bucket.name,
                items=[_summary(row) for row in bucket.items],
            )
            for bucket in view.categories
        ],
    )


@router.get("/activities/{activity_id}", response_model=ActivityResponse)
def get_activity(
    activity_id: UUID,
    viewer: CurrentUser | None = Depends(get_optional_user),
    service: ActivityService = Depends(get_activity_service),
) -> ActivityResponse:
    """Detail row; drafts only resolve for org members."""
    return _response(
        service.get_visible(
            activity_id, viewer.id if viewer else None
        )
    )


@router.get(
    "/orgs/{org_id}/activities", response_model=list[ActivitySummary]
)
def list_org_activities(
    org_id: UUID,
    trash: bool = Query(default=False),
    current: CurrentUser = Depends(get_current_user),
    service: ActivityService = Depends(get_activity_service),
) -> list[ActivitySummary]:
    """Member feed of every activity in the org; ?trash=1 is manager-only."""
    return [
        _summary(row)
        for row in service.list_org(org_id, current.id, trash)
    ]


@router.get(
    "/orgs/{org_id}/activities/by-slug/{slug}",
    response_model=ActivityResponse,
)
def get_activity_by_slug(
    org_id: UUID,
    slug: str,
    viewer: CurrentUser | None = Depends(get_optional_user),
    service: ActivityService = Depends(get_activity_service),
) -> ActivityResponse:
    """Pretty-URL resolution used by the public event page."""
    return _response(
        service.get_by_slug(
            org_id, slug, viewer.id if viewer else None
        )
    )


@router.post(
    "/orgs/{org_id}/activities",
    response_model=ActivityResponse,
    status_code=201,
)
def create_activity(
    org_id: UUID,
    body: ActivityBody,
    current: CurrentUser = Depends(get_current_user),
    service: ActivityService = Depends(get_activity_service),
) -> ActivityResponse:
    """Member with activity:create opens a draft activity."""
    return _response(
        service.create_activity(
            org_id, current.id, _fields(body, keep_slug=False)
        )
    )


@router.patch(
    "/orgs/{org_id}/activities/{activity_id}",
    response_model=ActivityResponse,
)
def update_activity(
    org_id: UUID,
    activity_id: UUID,
    body: ActivityBody,
    current: CurrentUser = Depends(get_current_user),
    service: ActivityService = Depends(get_activity_service),
) -> ActivityResponse:
    """Managers replace editable fields before completion."""
    return _response(
        service.update_activity(
            org_id, activity_id, current.id,
            _fields(body, keep_slug=True),
        )
    )


@router.post(
    "/orgs/{org_id}/activities/{activity_id}/status",
    response_model=ActivityResponse,
)
def transition_activity(
    org_id: UUID,
    activity_id: UUID,
    body: StatusBody,
    current: CurrentUser = Depends(get_current_user),
    service: ActivityService = Depends(get_activity_service),
) -> ActivityResponse:
    """Managers move the lifecycle: publish | ongoing | completed | cancelled."""
    return _response(
        service.set_status(
            org_id, activity_id, current.id, body.status
        )
    )


@router.delete(
    "/orgs/{org_id}/activities/{activity_id}",
    response_model=ActivityResponse | None,
    status_code=200,
)
def delete_activity(
    org_id: UUID,
    activity_id: UUID,
    hard: bool = Query(default=False),
    current: CurrentUser = Depends(get_current_user),
    service: ActivityDeleteService = Depends(get_activity_delete_service),
) -> ActivityResponse | Response:
    """Soft delete to trash by default; hard=true purges permanently."""
    if hard:
        service.hard_delete(org_id, activity_id, current.id)
        return Response(status_code=204)
    return _response(
        service.soft_delete(org_id, activity_id, current.id)
    )


@router.post(
    "/orgs/{org_id}/activities/{activity_id}/restore",
    response_model=ActivityResponse,
)
def restore_activity(
    org_id: UUID,
    activity_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: ActivityDeleteService = Depends(get_activity_delete_service),
) -> ActivityResponse:
    """Managers bring a soft-deleted activity back with its slug."""
    return _response(
        service.restore(org_id, activity_id, current.id)
    )
