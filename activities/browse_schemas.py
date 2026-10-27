"""Response models for the browse feed.

The public contract is BrowsePage. The signed-in view extends it with its
own item and facet fields; ActivitySummary stays frozen for the legacy list.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from activities.schemas import TagRef


class BrowseOrg(BaseModel):
    id: UUID
    name: str
    slug: str
    logo_url: str | None
    verified: bool


class BrowseItem(BaseModel):
    id: UUID
    org_id: UUID
    slug: str
    title: str
    status: str
    phase: str
    start_at: datetime | None
    end_at: datetime | None
    city: str | None
    location: str | None
    is_remote: bool
    hours_awarded: float
    category_id: UUID | None
    tags: list[TagRef]
    excerpt: str
    cover_url: str | None
    max_participants: int | None
    registered_count: int | None
    seats_left: int | None
    registration_deadline: datetime | None
    registration_open: bool
    org: BrowseOrg
    # Viewer-agnostic: open now and asks nothing beyond a click (no form, no slots).
    quick_apply: bool = False


class CityFacet(BaseModel):
    city: str
    count: int


class CategoryFacet(BaseModel):
    """A catalog category that has matching activities, with its count."""

    category_id: UUID
    name: str
    count: int


class TagFacet(BaseModel):
    """A community tag on matching activities, most used first."""

    slug: str
    name: str
    count: int


class BrowseFacets(BaseModel):
    cities: list[CityFacet]
    categories: list[CategoryFacet]
    tags: list[TagFacet]


class BrowseEnvelope(BaseModel):
    items: list[BrowseItem]
    total: int
    truncated: bool
    facets: BrowseFacets


class BrowsePage(BrowseEnvelope):
    # Continuation token for the next window; set only when truncated.
    next_cursor: str | None = None


class MyRegistration(BaseModel):
    """The caller's own registration status; never shown on the public feed."""

    registration_id: UUID
    status: str
    registered_at: datetime | None


class MineBrowseItem(BrowseItem):
    my_registration: MyRegistration


class StatusFacet(BaseModel):
    status: str
    count: int


class MineFacets(BrowseFacets):
    my_status: list[StatusFacet]


class MineBrowsePage(BrowseEnvelope):
    items: list[MineBrowseItem]
    facets: MineFacets
