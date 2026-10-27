"""Cross-org activity feed: one request for every org the caller belongs to."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from activities.mine_schemas import (
    MyActivitiesResponse,
    MyActivityItem,
    MyActivityOrg,
)
from activities.mine_service import MyActivitiesService
from activities.router import _summary
from core.dependencies import CurrentUser, get_current_user
from core.dependencies_activity_feed import get_my_activities_service

router = APIRouter(tags=["activities"])


@router.get("/me/activities", response_model=MyActivitiesResponse)
def my_activities(
    trash: bool = Query(default=False),
    current: CurrentUser = Depends(get_current_user),
    service: MyActivitiesService = Depends(get_my_activities_service),
) -> MyActivitiesResponse:
    """Activities of every org the caller belongs to.

    ?trash=1 lists trashed rows of the orgs the caller can manage only.
    """
    feed = service.feed(current.id, trash)
    return MyActivitiesResponse(
        items=[
            MyActivityItem(
                **_summary(row.activity).model_dump(),
                can_manage=row.can_manage,
                can_delete=row.can_delete,
            )
            for row in feed.rows
        ],
        orgs=[
            MyActivityOrg(
                id=grant.org.id,  # type: ignore[attr-defined]
                name=grant.org.name,  # type: ignore[attr-defined]
                slug=grant.org.slug,  # type: ignore[attr-defined]
                kind=getattr(grant.org, "org_type", None) or "organization",
                can_create=grant.can_create,
                can_manage=grant.can_manage,
                can_delete=grant.can_delete,
                activity_count=grant.activity_count,
                logo_url=grant.logo_url,
            )
            for grant in feed.orgs
        ],
    )
