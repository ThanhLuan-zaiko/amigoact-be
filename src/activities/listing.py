"""Lists of activities: the public search and one organization's activities."""

import uuid
from typing import Any, Literal

from fastapi import status
from sqlalchemy import Select, func
from sqlalchemy.orm import Session

from src.activities.queries import summary_query, to_summary
from src.activities.rules import CANCELLED, COMPLETED, DRAFT, PUBLISHED
from src.activities.schemas import ActivityPage
from src.activities.tags import tags_by_activity, with_activity_tag
from src.auth.errors import api_error
from src.models.activities import Activity
from src.models.organizations import Organization
from src.organizations.access import get_access
from src.pagination import count_rows

# What the tabs of an organization's activity list show. No filter means every
# activity people can see. Drafts have their own list, only for managers.
OrgFilter = Literal["upcoming", "completed", "cancelled", "draft"]


def _page(db: Session, query: Select[Any], limit: int, offset: int) -> ActivityPage:
    rows = db.execute(query.limit(limit + 1).offset(offset)).all()
    items = [to_summary(row) for row in rows[:limit]]
    tags = tags_by_activity(db, [item.id for item in items])
    for item in items:
        item.tags = tags[item.id]
    return ActivityPage(
        items=items,
        next_offset=offset + limit if len(rows) > limit else None,
        total=count_rows(db, query),
    )


def list_public_activities(
    db: Session,
    search: str | None,
    city: str | None,
    limit: int,
    offset: int,
    tag: str | None = None,
) -> ActivityPage:
    """Published activities that have not started, soonest first."""

    query = summary_query().where(
        Activity.status == PUBLISHED, Activity.start_at > func.now()
    )

    if search:
        query = query.where(Activity.title.icontains(search, autoescape=True))

    if city:
        query = query.where(Activity.city.icontains(city, autoescape=True))
    query = with_activity_tag(query, tag).order_by(Activity.start_at, Activity.id)
    return _page(db, query, limit, offset)


def org_filter_query(query: Select[Any], view: OrgFilter | None) -> Select[Any]:
    """Narrow an organization's activities to one tab, in the order that tab reads."""
    if view == "upcoming":
        # Soonest first, like the public search.
        return query.where(
            Activity.status == PUBLISHED, Activity.start_at > func.now()
        ).order_by(Activity.start_at, Activity.id)
    if view == "draft":
        query = query.where(Activity.status == DRAFT)
    elif view == "completed":
        query = query.where(Activity.status == COMPLETED)
    elif view == "cancelled":
        query = query.where(Activity.status == CANCELLED)
    else:
        query = query.where(Activity.status != DRAFT)
    return query.order_by(Activity.start_at.desc().nulls_first(), Activity.id.desc())


def list_organization_activities(
    db: Session,
    org: Organization,
    user_id: uuid.UUID | None,
    limit: int,
    offset: int,
    view: OrgFilter | None = None,
    tag: str | None = None,
) -> ActivityPage:
    """Activities people can see. Drafts are a separate list for managers."""
    if view == "draft" and (
        user_id is None or not get_access(db, org, user_id).can_manage
    ):
        raise api_error(status.HTTP_403_FORBIDDEN, "organization_forbidden")
    query = with_activity_tag(summary_query().where(Activity.org_id == org.id), tag)
    return _page(db, org_filter_query(query, view), limit, offset)
