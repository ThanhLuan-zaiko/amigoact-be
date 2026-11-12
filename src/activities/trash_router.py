"""Routes for the activity trash: list, restore, and remove for good."""

from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from src.activities import service, trash
from src.activities.schemas import ActivityDetail, ActivityTrashItem, ActivityTrashPage
from src.activities.trash_rules import may_purge, purge_at
from src.auth.deps import CurrentPrincipal, Db
from src.organizations.access import get_access
from src.organizations.service import load_organization
from src.validation import Uuid7

router = APIRouter(tags=["activities"])

Slug = Annotated[str, Path(pattern=r"^[A-Za-z0-9-]{1,80}$")]
Limit = Annotated[int, Query(ge=1, le=50)]


@router.get("/organizations/{slug}/activity-trash")
def activity_trash(
    slug: Slug,
    principal: CurrentPrincipal,
    db: Db,
    before: Annotated[Uuid7 | None, Query()] = None,
    limit: Limit = 20,
) -> ActivityTrashPage:
    org = load_organization(db, slug)
    rows = trash.list_trash(db, org, principal.user.id, before=before, limit=limit)
    can_purge = may_purge(get_access(db, org, principal.user.id))
    items = [
        ActivityTrashItem(
            id=activity.id,
            title=activity.title,
            start_at=activity.start_at,
            deleted_at=activity.deleted_at,
            purge_at=purge_at(activity.deleted_at),
            can_purge=can_purge,
        )
        for activity in rows[:limit]
        if activity.deleted_at is not None
    ]
    next_before = rows[limit - 1].id if len(rows) > limit else None
    return ActivityTrashPage(items=items, next_before=next_before)


@router.post("/activities/{activity_id}/restore")
def restore_activity(
    activity_id: Uuid7, principal: CurrentPrincipal, db: Db
) -> ActivityDetail:
    activity = trash.restore_activity(db, activity_id, principal.user.id)
    return service.activity_detail(db, activity, principal.user.id)


@router.delete(
    "/activities/{activity_id}/purge", status_code=status.HTTP_204_NO_CONTENT
)
def purge_activity(activity_id: Uuid7, principal: CurrentPrincipal, db: Db) -> None:
    trash.purge_activity(db, activity_id, principal.user.id)
