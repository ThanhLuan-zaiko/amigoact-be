"""Time windows for the public feed: date bounds, scan cuts and cursors.

Feeds are read as bounded clustering ranges. A scan returns at most limit + 1
rows in scan order; the extra row reveals overflow. cut_window decides which
rows belong to this window and where the next one starts.

A cut is a start_at value B. The window keeps the rows strictly before B in
scan order, and the next window starts at B inclusive, so no row is lost or
repeated. One exception: when every fetched row shares B, they are kept and
the next window starts strictly after B. A tie group is then complete only
up to the scan limit, which is the documented edge of this rule.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeVar

from core.exceptions import DomainError

T = TypeVar("T")
PUBLIC_PHASES = ("upcoming", "ongoing", "past")


class InvalidCursorError(DomainError):
    """A cursor that is malformed or belongs to another query."""

    code = "VALIDATION_ERROR"
    status = 422


@dataclass(frozen=True)
class Bound:
    """One edge of a start_at range; inclusive means the edge row itself counts."""

    value: datetime
    inclusive: bool


@dataclass(frozen=True)
class Scan:
    """One clustering read: a partition, its start_at range and a row limit."""

    partition: str
    lower: Bound | None
    upper: Bound | None
    limit: int


@dataclass(frozen=True)
class Cut:
    """Where the current window ends. A None boundary means nothing overflowed."""

    boundary: datetime | None = None
    inclusive: bool = True


@dataclass(frozen=True)
class Cursor:
    """Continuation state: the next window starts at the boundary.

    org_id is None for the public feed and the organization's id otherwise.
    """

    phase: str
    org_id: str | None
    boundary: datetime
    inclusive: bool


def tighten_lower(*bounds: Bound | None) -> Bound | None:
    """Strictest lower edge: the latest value, exclusive on a tie."""
    chosen: Bound | None = None
    for bound in bounds:
        if bound is not None and (
            chosen is None
            or bound.value > chosen.value
            or (bound.value == chosen.value and not bound.inclusive)
        ):
            chosen = bound
    return chosen


def tighten_upper(*bounds: Bound | None) -> Bound | None:
    """Strictest upper edge: the earliest value, exclusive on a tie."""
    chosen: Bound | None = None
    for bound in bounds:
        if bound is not None and (
            chosen is None
            or bound.value < chosen.value
            or (bound.value == chosen.value and not bound.inclusive)
        ):
            chosen = bound
    return chosen


def is_empty(lower: Bound | None, upper: Bound | None) -> bool:
    """True when no start_at can satisfy both edges."""
    if lower is None or upper is None:
        return False
    if lower.value != upper.value:
        return lower.value > upper.value
    return not (lower.inclusive and upper.inclusive)


def _dates(
    starts_from: datetime | None, starts_to: datetime | None
) -> tuple[Bound | None, Bound | None]:
    """The query's [from, to) range as edges: from inclusive, to exclusive."""
    return (
        Bound(starts_from, True) if starts_from is not None else None,
        Bound(starts_to, False) if starts_to is not None else None,
    )


def _cursor_edge(cursor: Cursor | None) -> Bound | None:
    return Bound(cursor.boundary, cursor.inclusive) if cursor else None


def public_scans(
    phase: str,
    now: datetime,
    starts_from: datetime | None,
    starts_to: datetime | None,
    cursor: Cursor | None,
    *,
    status_limit: int,
    recent_limit: int,
) -> list[Scan]:
    """Status-feed reads for one public phase, narrowed by dates and cursor.

    Upcoming is one ascending read. Ongoing and past pair an explicit status
    partition with recently started published rows, because organizers often
    never flip published to ongoing or completed. Empty reads are dropped.
    """
    from_edge, to_edge = _dates(starts_from, starts_to)
    edge = _cursor_edge(cursor)
    if phase == "upcoming":
        scans = [
            Scan(
                "published",
                tighten_lower(Bound(now, False), from_edge, edge),
                to_edge,
                status_limit,
            )
        ]
    else:
        flagged = "ongoing" if phase == "ongoing" else "completed"
        scans = [
            Scan(flagged, from_edge, tighten_upper(to_edge, edge), status_limit),
            Scan(
                "published",
                from_edge,
                tighten_upper(Bound(now, True), to_edge, edge),
                recent_limit,
            ),
        ]
    return [s for s in scans if not is_empty(s.lower, s.upper)]


def org_scans(
    org_id: str,
    starts_from: datetime | None,
    starts_to: datetime | None,
    cursor: Cursor | None,
    limit: int,
) -> list[Scan]:
    """One organization's feed, newest first; the phase is judged after the read."""
    from_edge, to_edge = _dates(starts_from, starts_to)
    scan = Scan(
        org_id, from_edge, tighten_upper(to_edge, _cursor_edge(cursor)), limit
    )
    return [] if is_empty(scan.lower, scan.upper) else [scan]


def _before(moment: datetime, boundary: datetime, ascending: bool) -> bool:
    return moment < boundary if ascending else moment > boundary


def cut_window(
    sources: Sequence[Sequence[T]],
    limits: Sequence[int],
    key: Callable[[T], datetime],
    *,
    ascending: bool,
) -> tuple[list[T], Cut]:
    """Rows that belong to this window, plus where the next one starts.

    Each source holds up to limit + 1 rows in scan order. Only a source with
    more than limit rows overflows, and its first excluded row sets a cut.
    The earliest cut in scan order wins, so every source keeps the rows
    before it and the rest are read again by the next window.
    """
    cuts = [
        key(rows[limit])
        for rows, limit in zip(sources, limits, strict=True)
        if len(rows) > limit
    ]
    if not cuts:
        return [row for rows in sources for row in rows], Cut()
    boundary = min(cuts) if ascending else max(cuts)
    kept = [
        row
        for rows in sources
        for row in rows
        if _before(key(row), boundary, ascending)
    ]
    if kept:
        return kept, Cut(boundary, inclusive=True)
    tied = [row for rows in sources for row in rows if key(row) == boundary]
    return tied, Cut(boundary, inclusive=False)


def cursor_after(phase: str, scope: str | None, cut: Cut) -> str | None:
    """Token for the window after this one, or None when this one was complete."""
    if cut.boundary is None:
        return None
    return _encode(Cursor(phase, scope, cut.boundary, cut.inclusive))


def resolve_cursor(token: str | None, phase: str, scope: str | None) -> Cursor | None:
    """Decode a continuation token and check that it belongs to this query."""
    if token is None:
        return None
    cursor = _decode(token)
    if cursor.phase != phase or cursor.org_id != scope:
        raise InvalidCursorError("Cursor does not match this query.")
    return cursor


def _encode(cursor: Cursor) -> str:
    payload = {
        "p": cursor.phase,
        "o": cursor.org_id,
        "b": cursor.boundary.isoformat(),
        "i": cursor.inclusive,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _decode(token: str) -> Cursor:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        payload = json.loads(raw.decode("utf-8"))
        boundary = datetime.fromisoformat(payload["b"])
    except (ValueError, KeyError, TypeError) as err:
        raise InvalidCursorError("Cursor is malformed.") from err
    phase, org_id, inclusive = payload.get("p"), payload.get("o"), payload.get("i")
    if (
        phase not in PUBLIC_PHASES
        or not isinstance(inclusive, bool)
        or (org_id is not None and not isinstance(org_id, str))
    ):
        raise InvalidCursorError("Cursor is malformed.")
    if boundary.tzinfo is not None:
        boundary = boundary.astimezone(UTC).replace(tzinfo=None)
    return Cursor(phase, org_id, boundary, inclusive)
