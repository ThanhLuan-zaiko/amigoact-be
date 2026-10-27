"""Browse feed value types and the pure ordering and filtering rules.

Kept apart from the service so each module stays under the line limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import NamedTuple
from uuid import UUID

from activities.browse_facets import CategoryCount, TagCount, tag_slugs
from activities.browse_filters import utc_naive
from activities.browse_interfaces import MyRegistrationBrief
from activities.model import Activity
from orgs.listing import fold_search_text

_EPOCH = datetime(1970, 1, 1)
_EXCERPT_CHARS = 160
# 'My registrations' order: live first, then past, then cancelled last.
_MINE_RANK = {"upcoming": 0, "ongoing": 0, "past": 1, "cancelled": 2}


@dataclass(frozen=True)
class BrowseQuery:
    """Normalized filters; the router maps URL parameters onto this."""

    phase: str = "upcoming"
    q: str | None = None
    category_id: UUID | None = None
    tag_slug: str | None = None
    city: str | None = None
    mode: str | None = None
    starts_from: datetime | None = None
    starts_to: datetime | None = None
    registration_open_only: bool = False
    sort: str = "start"
    limit: int = 12
    offset: int = 0
    my_status: str | None = None
    # Scopes the public feed to one organization's slug.
    org_slug: str | None = None
    # Opaque token from the previous window; None starts at the beginning.
    cursor: str | None = None


@dataclass(frozen=True)
class BrowseOrgView:
    id: UUID
    name: str
    slug: str
    logo_url: str | None
    verified: bool


@dataclass(frozen=True)
class BrowseCard:
    activity: Activity
    phase: str
    org: BrowseOrgView
    cover_url: str | None
    registered_count: int | None
    seats_left: int | None
    registration_open: bool
    excerpt: str
    my_registration: MyRegistrationBrief | None = None
    # Viewer-agnostic: an open activity that asks nothing beyond a click.
    quick_apply: bool = False


@dataclass(frozen=True)
class BrowseResult:
    cards: list[BrowseCard]
    total: int
    truncated: bool
    cities: list[tuple[str, int]] = field(default_factory=list)
    categories: list[CategoryCount] = field(default_factory=list)
    tags: list[TagCount] = field(default_factory=list)
    my_statuses: list[tuple[str, int]] = field(default_factory=list)
    next_cursor: str | None = None


class Match(NamedTuple):
    row: Activity
    phase: str
    org: object
    brief: MyRegistrationBrief | None


def seconds(moment: datetime | None) -> float:
    return ((moment or _EPOCH) - _EPOCH).total_seconds()


def excerpt(text: str | None) -> str:
    flat = " ".join((text or "").split())
    if len(flat) <= _EXCERPT_CHARS:
        return flat
    return flat[: _EXCERPT_CHARS - 3].rstrip() + "..."


def keep_match(match: Match, query: BrowseQuery, skip: str = "") -> bool:
    """True when the match passes every filter except the one named by skip."""
    checks = {
        "category": query.category_id is None
        or match.row.category_id == query.category_id,
        "tag": query.tag_slug is None or query.tag_slug in tag_slugs(match.row),
        "city": not query.city
        or fold_search_text(match.row.city or "")
        == fold_search_text(query.city),
        "status": not query.my_status
        or (match.brief is not None and match.brief.status == query.my_status),
    }
    return all(ok for name, ok in checks.items() if name != skip)


def public_order(matches: list[Match], query: BrowseQuery) -> list[Match]:
    if query.sort == "published":
        return sorted(
            matches,
            key=lambda m: seconds(utc_naive(m.row.published_at)),
            reverse=True,
        )
    return sorted(
        matches,
        key=lambda m: seconds(utc_naive(m.row.start_at)),
        reverse=query.phase == "past",
    )


def mine_order(matches: list[Match]) -> list[Match]:
    def key(match: Match) -> tuple[int, float]:
        rank = _MINE_RANK[match.phase]
        start = seconds(utc_naive(match.row.start_at))
        return (rank, -start if rank == 1 else start)

    return sorted(matches, key=key)


