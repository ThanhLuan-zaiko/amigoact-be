"""HTTP layer for the browse feed: public phase tabs and the signed-in view.

Mounted before the activities router: /activities/browse must not be
captured by /activities/{activity_id}.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from activities.browse_filters import utc_naive
from activities.browse_schemas import (
    BrowseFacets,
    BrowseItem,
    BrowseOrg,
    BrowsePage,
    CategoryFacet,
    CityFacet,
    MineBrowseItem,
    MineBrowsePage,
    MineFacets,
    MyRegistration,
    StatusFacet,
    TagFacet,
)
from activities.browse_service import (
    ActivityBrowseService,
    BrowseCard,
    BrowseQuery,
    BrowseResult,
)
from activities.model import tag_slug
from activities.schemas import TagRef
from core.dependencies import CurrentUser, get_current_user
from core.dependencies_activity_feed import get_activity_browse_service
from core.security import utc_aware

router = APIRouter(tags=["activities"])


def _item(card: BrowseCard) -> BrowseItem:
    row = card.activity
    return BrowseItem(
        id=row.id,
        org_id=row.org_id,
        slug=row.slug,
        title=row.title,
        status=row.status,
        phase=card.phase,
        start_at=utc_aware(row.start_at),
        end_at=utc_aware(row.end_at),
        city=row.city,
        location=row.location,
        is_remote=bool(row.is_remote),
        hours_awarded=float(row.hours_awarded or 0.0),
        category_id=row.category_id,
        tags=[
            TagRef(name=name, slug=tag_slug(name))
            for name in row.tag_names or []
        ],
        excerpt=card.excerpt,
        cover_url=card.cover_url,
        max_participants=row.max_participants,
        registered_count=card.registered_count,
        seats_left=card.seats_left,
        registration_deadline=utc_aware(row.registration_deadline),
        registration_open=card.registration_open,
        quick_apply=card.quick_apply,
        org=BrowseOrg(
            id=card.org.id,
            name=card.org.name,
            slug=card.org.slug,
            logo_url=card.org.logo_url,
            verified=card.org.verified,
        ),
    )


def _facet_fields(result: BrowseResult) -> dict[str, list]:
    """Facet lists shared by the public and signed-in responses."""
    return {
        "cities": [
            CityFacet(city=city, count=count) for city, count in result.cities
        ],
        "categories": [
            CategoryFacet(category_id=c.category_id, name=c.name, count=c.count)
            for c in result.categories
        ],
        "tags": [
            TagFacet(slug=t.slug, name=t.name, count=t.count)
            for t in result.tags
        ],
    }


def _page(result: BrowseResult) -> BrowsePage:
    return BrowsePage(
        items=[_item(card) for card in result.cards],
        total=result.total,
        truncated=result.truncated,
        facets=BrowseFacets(**_facet_fields(result)),
        next_cursor=result.next_cursor,
    )


def _mine_page(result: BrowseResult) -> MineBrowsePage:
    items = []
    for card in result.cards:
        brief = card.my_registration
        if brief is None:  # the signed-in path always carries a brief
            continue
        base = _item(card).model_dump()
        items.append(
            MineBrowseItem(
                **base,
                my_registration=MyRegistration(
                    registration_id=brief.registration_id,
                    status=brief.status,
                    registered_at=utc_aware(brief.registered_at),
                ),
            )
        )
    return MineBrowsePage(
        items=items,
        total=result.total,
        truncated=result.truncated,
        facets=MineFacets(
            **_facet_fields(result),
            my_status=[
                StatusFacet(status=status, count=count)
                for status, count in result.my_statuses
            ],
        ),
    )


@router.get("/activities/browse", response_model=BrowsePage)
def browse_activities(
    phase: str = Query(default="upcoming", pattern="^(upcoming|ongoing|past)$"),
    q: str | None = Query(default=None, max_length=100),
    category_id: UUID | None = Query(default=None),
    tag: str | None = Query(default=None, max_length=60),
    city: str | None = Query(default=None, max_length=80),
    mode: str | None = Query(default=None, pattern="^(online|offline)$"),
    starts_from: datetime | None = Query(default=None),
    starts_to: datetime | None = Query(default=None),
    registration_open: bool = Query(default=False),
    sort: str = Query(default="start", pattern="^(start|published)$"),
    org: str | None = Query(default=None, max_length=80),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=12, ge=1, le=30),
    offset: int = Query(default=0, ge=0, le=500),
    service: ActivityBrowseService = Depends(get_activity_browse_service),
) -> BrowsePage:
    """Public browse: one phase window, filtered, sorted and paged."""
    slug = tag_slug(tag) if tag else ""
    result = service.browse(
        BrowseQuery(
            phase=phase,
            q=(q or "").strip() or None,
            category_id=category_id,
            tag_slug=slug or None,
            city=(city or "").strip() or None,
            mode=mode,
            starts_from=utc_naive(starts_from),
            starts_to=utc_naive(starts_to),
            registration_open_only=registration_open,
            sort=sort,
            org_slug=(org or "").strip() or None,
            cursor=cursor,
            limit=limit,
            offset=offset,
        )
    )
    return _page(result)


@router.get("/activities/{activity_id}/card", response_model=BrowseItem)
def activity_card(
    activity_id: UUID,
    service: ActivityBrowseService = Depends(get_activity_browse_service),
) -> BrowseItem:
    """One public card for the detail page, in the feed's item shape."""
    return _item(service.card_for(activity_id))


@router.get("/activities/browse/mine", response_model=MineBrowsePage)
def browse_my_activities(
    q: str | None = Query(default=None, max_length=100),
    category_id: UUID | None = Query(default=None),
    tag: str | None = Query(default=None, max_length=60),
    city: str | None = Query(default=None, max_length=80),
    mode: str | None = Query(default=None, pattern="^(online|offline)$"),
    my_status: str | None = Query(
        default=None,
        pattern="^(pending|approved|waitlisted|attended|rejected|cancelled)$",
    ),
    starts_from: datetime | None = Query(default=None),
    starts_to: datetime | None = Query(default=None),
    registration_open: bool = Query(default=False),
    limit: int = Query(default=12, ge=1, le=30),
    offset: int = Query(default=0, ge=0, le=500),
    current: CurrentUser = Depends(get_current_user),
    service: ActivityBrowseService = Depends(get_activity_browse_service),
) -> MineBrowsePage:
    """The caller's own registrations: status chips plus the same filters."""
    slug = tag_slug(tag) if tag else ""
    result = service.browse_mine(
        current.id,
        BrowseQuery(
            q=(q or "").strip() or None,
            category_id=category_id,
            tag_slug=slug or None,
            city=(city or "").strip() or None,
            mode=mode,
            my_status=my_status,
            starts_from=utc_naive(starts_from),
            starts_to=utc_naive(starts_to),
            registration_open_only=registration_open,
            limit=limit,
            offset=offset,
        ),
    )
    return _mine_page(result)
