"""Browse feed: public phase windows and the signed-in 'my registrations' view.

One pipeline serves both. Candidate rows are hydrated and filtered in
memory. Each facet counts the rows that pass every filter except its own,
and only the page that is returned pays for org, cover and seat reads.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from activities.browse_cover import cover_url
from activities.browse_facets import (
    category_counts,
    city_counts,
    status_counts,
    tag_counts,
)
from activities.browse_filters import (
    classify_phase,
    is_registration_open,
    matches_query,
    utc_naive,
)
from activities.browse_interfaces import (
    BrowseIndex,
    MyRegistrationBrief,
    RegistrationBriefs,
    SeatCounter,
)
from activities.browse_types import (
    BrowseCard,
    BrowseOrgView,
    BrowseQuery,
    BrowseResult,
    Match,
    excerpt,
    keep_match,
    mine_order,
    public_order,
)
from activities.edge_interfaces import ActivityMediaStore
from activities.interfaces import CategoryStore
from activities.model import Activity
from core.security import utcnow
from orgs.brand import brand_url
from orgs.interfaces import MediaRepository, OrgRepository
from orgs.listing import fold_search_text

class ActivityBrowseService:
    """Read-only feed; the public path never sees per-viewer data."""

    def __init__(
        self,
        index: BrowseIndex,
        orgs: OrgRepository,
        entries: ActivityMediaStore,
        media: MediaRepository,
        seats: SeatCounter,
        briefs: RegistrationBriefs,
        categories: CategoryStore,
    ) -> None:
        self._index = index
        self._orgs = orgs
        self._entries = entries
        self._media = media
        self._seats = seats
        self._briefs = briefs
        self._categories = categories

    def browse(
        self, query: BrowseQuery, now: datetime | None = None
    ) -> BrowseResult:
        moment = utc_naive(now or utcnow())
        ids, truncated = self._index.candidates(query.phase, moment)
        return self._run(
            self._index.hydrate(ids), query, moment, truncated, None
        )

    def browse_mine(
        self, user_id: UUID, query: BrowseQuery, now: datetime | None = None
    ) -> BrowseResult:
        """Only activities the caller registered for, cancelled ones too."""
        moment = utc_naive(now or utcnow())
        briefs = self._briefs.briefs_for(user_id)
        return self._run(
            self._index.hydrate(list(briefs)), query, moment, False, briefs
        )

    def _run(
        self,
        rows: list[Activity],
        query: BrowseQuery,
        now: datetime,
        truncated: bool,
        briefs: dict[UUID, MyRegistrationBrief] | None,
    ) -> BrowseResult:
        term = fold_search_text(query.q) if query.q else ""
        orgs: dict[UUID, object | None] = {}
        matches: list[Match] = []
        for row in rows:
            match = self._match(row, query, now, term, orgs, briefs)
            if match is not None:
                matches.append(match)
        # Every facet counts the rows that pass all filters except its own,
        # so picking one value never hides its alternatives.
        names = self._category_names(matches)
        categories = category_counts(
            [m.row for m in matches if keep_match(m, query, skip="category")],
            names,
        )
        tags = tag_counts(
            [m.row for m in matches if keep_match(m, query, skip="tag")]
        )
        cities = city_counts(
            [m.row for m in matches if keep_match(m, query, skip="city")]
        )
        my_statuses = (
            status_counts(
                m.brief.status
                for m in matches
                if m.brief is not None and keep_match(m, query, skip="status")
            )
            if briefs is not None
            else []
        )
        final = [m for m in matches if keep_match(m, query)]
        ordered = (
            mine_order(final) if briefs is not None
            else public_order(final, query)
        )
        page = ordered[query.offset : query.offset + query.limit]
        return BrowseResult(
            cards=[self._card(m, now) for m in page],
            total=len(ordered),
            truncated=truncated,
            cities=cities,
            categories=categories,
            tags=tags,
            my_statuses=my_statuses,
        )

    def _match(
        self,
        row: Activity,
        query: BrowseQuery,
        now: datetime,
        term: str,
        orgs: dict[UUID, object | None],
        briefs: dict[UUID, MyRegistrationBrief] | None,
    ) -> Match | None:
        """Filters every facet shares: phase, org, mode, dates, text, status.

        Category, tag, city and my-status are applied later in keep_match, so
        each facet can count without its own filter.
        """
        if row.deleted_at is not None:
            return None
        brief = None
        phase = classify_phase(
            row.status,
            utc_naive(row.start_at),
            utc_naive(row.end_at),
            now,
        )
        if briefs is None:
            if phase != query.phase:
                return None
        else:
            brief = briefs.get(row.id)
            if brief is None:
                return None
            if phase is None and row.status == "cancelled":
                phase = "cancelled"
            if phase is None:
                return None
        org = self._org(row.org_id, orgs)
        if org is None:
            return None
        if query.mode == "online" and not row.is_remote:
            return None
        if query.mode == "offline" and row.is_remote:
            return None
        start = utc_naive(row.start_at)
        if query.starts_from is not None and (
            start is None or start < query.starts_from
        ):
            return None
        if query.starts_to is not None and (
            start is None or start >= query.starts_to
        ):
            return None
        if query.registration_open_only and not is_registration_open(
            row.status, utc_naive(row.registration_deadline), phase, now
        ):
            return None
        if term and not matches_query(
            term,
            [row.title, row.location, row.city, org.name, *(row.tag_names or [])],
        ):
            return None
        return Match(row, phase, org, brief)

    def _org(
        self, org_id: UUID, cache: dict[UUID, object | None]
    ) -> object | None:
        """Each distinct org is read once per request; hidden orgs drop out."""
        if org_id not in cache:
            org = self._orgs.get_by_id(org_id)
            live = (
                org is not None
                and getattr(org, "deleted_at", None) is None
                and (getattr(org, "status", "active") or "active") == "active"
            )
            cache[org_id] = org if live else None
        return cache[org_id]

    def _category_names(self, matches: list[Match]) -> dict[UUID, str]:
        """Catalog names for the categories present, one read per category."""
        names: dict[UUID, str] = {}
        seen: set[UUID] = set()
        for match in matches:
            category_id = match.row.category_id
            if category_id is None or category_id in seen:
                continue
            seen.add(category_id)
            category = self._categories.get(category_id)
            if category is not None:
                names[category_id] = category.name
        return names

    def _card(self, match: Match, now: datetime) -> BrowseCard:
        row, org = match.row, match.org
        registered: int | None = None
        seats_left: int | None = None
        if row.max_participants is not None:
            registered = self._seats.registered_count(row.id)
            seats_left = max(0, row.max_participants - registered)
        return BrowseCard(
            activity=row,
            phase=match.phase,
            org=BrowseOrgView(
                id=org.id,
                name=org.name,
                slug=org.slug,
                logo_url=brand_url(
                    self._media, org.id, org.logo_media_id, "logo"
                ),
                verified=getattr(org, "verified_at", None) is not None,
            ),
            cover_url=cover_url(self._entries, self._media, row.id),
            registered_count=registered,
            seats_left=seats_left,
            registration_open=is_registration_open(
                row.status,
                utc_naive(row.registration_deadline),
                match.phase,
                now,
            ),
            excerpt=excerpt(row.description),
            my_registration=match.brief,
        )
