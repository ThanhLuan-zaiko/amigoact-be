"""Pure window rules: date edges, scan cuts and cursor tokens."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from activities.browse_window import (
    Bound,
    Cursor,
    Cut,
    InvalidCursorError,
    cursor_after,
    cut_window,
    is_empty,
    org_scans,
    public_scans,
    resolve_cursor,
    tighten_lower,
    tighten_upper,
)

NOW = datetime(2026, 10, 25, 9, 0)


@dataclass(frozen=True)
class Row:
    name: str
    start_at: datetime


def at(hours: int) -> datetime:
    return NOW + timedelta(hours=hours)


def _key(row: Row) -> datetime:
    return row.start_at


def _rows(*hours: int) -> list[Row]:
    return [Row(f"e{h}", at(h)) for h in hours]


def _names(rows: list[Row]) -> list[str]:
    return [row.name for row in rows]


# --- edges -----------------------------------------------------------------


def test_tighten_keeps_the_strictest_edges() -> None:
    assert tighten_lower(Bound(at(1), True), Bound(at(2), True)) == Bound(at(2), True)
    assert tighten_lower(Bound(at(2), True), Bound(at(2), False)) == Bound(at(2), False)
    assert tighten_upper(Bound(at(3), True), Bound(at(2), True)) == Bound(at(2), True)
    assert tighten_upper(Bound(at(2), True), Bound(at(2), False)) == Bound(at(2), False)
    assert tighten_lower(None, None) is None


def test_empty_ranges_are_detected() -> None:
    assert is_empty(Bound(at(2), True), Bound(at(1), False))
    assert is_empty(Bound(at(2), True), Bound(at(2), False))
    assert not is_empty(Bound(at(2), True), Bound(at(2), True))
    assert not is_empty(None, Bound(at(1), False))


# --- public scans ----------------------------------------------------------


def test_upcoming_reads_ascending_after_now() -> None:
    (scan,) = public_scans(
        "upcoming", NOW, None, None, None, status_limit=5, recent_limit=3
    )
    assert scan.partition == "published"
    assert scan.lower == Bound(NOW, False)
    assert scan.upper is None
    assert scan.limit == 5


def test_upcoming_date_range_narrows_both_edges() -> None:
    (scan,) = public_scans(
        "upcoming", NOW, at(48), at(72), None, status_limit=5, recent_limit=3
    )
    assert scan.lower == Bound(at(48), True)
    assert scan.upper == Bound(at(72), False)


def test_range_ending_before_now_reads_nothing() -> None:
    assert (
        public_scans(
            "upcoming", NOW, None, at(-1), None, status_limit=5, recent_limit=3
        )
        == []
    )


def test_ongoing_pairs_the_flagged_partition_with_recent_published() -> None:
    flagged, recent = public_scans(
        "ongoing", NOW, None, None, None, status_limit=5, recent_limit=3
    )
    assert flagged.partition == "ongoing"
    assert flagged.lower is None and flagged.upper is None
    assert recent.partition == "published"
    assert recent.upper == Bound(NOW, True)
    assert recent.limit == 3


def test_past_stops_at_an_earlier_range_end() -> None:
    flagged, recent = public_scans(
        "past", NOW, None, at(-10), None, status_limit=5, recent_limit=3
    )
    assert flagged.partition == "completed"
    assert flagged.upper == Bound(at(-10), False)
    assert recent.upper == Bound(at(-10), False)


def test_cursor_bounds_the_descending_side() -> None:
    cursor = Cursor("past", None, at(-5), False)
    flagged, recent = public_scans(
        "past", NOW, None, None, cursor, status_limit=5, recent_limit=3
    )
    assert flagged.upper == Bound(at(-5), False)
    assert recent.upper == Bound(at(-5), False)


def test_cursor_bounds_the_ascending_side() -> None:
    cursor = Cursor("upcoming", None, at(4), True)
    (scan,) = public_scans(
        "upcoming", NOW, None, None, cursor, status_limit=5, recent_limit=3
    )
    assert scan.lower == Bound(at(4), True)


def test_org_scans_read_within_the_date_range() -> None:
    (scan,) = org_scans("org", at(1), at(5), None, 7)
    assert scan.lower == Bound(at(1), True)
    assert scan.upper == Bound(at(5), False)
    assert scan.limit == 7


def test_org_scans_skip_an_empty_range() -> None:
    assert org_scans("org", at(5), at(1), None, 7) == []


# --- cuts ------------------------------------------------------------------


def test_window_without_overflow_keeps_everything() -> None:
    kept, cut = cut_window([_rows(1, 2)], [5], _key, ascending=True)
    assert _names(kept) == ["e1", "e2"]
    assert cut == Cut()


def test_ascending_cut_keeps_rows_before_the_first_excluded_row() -> None:
    kept, cut = cut_window([_rows(1, 2, 3)], [2], _key, ascending=True)
    assert _names(kept) == ["e1", "e2"]
    assert cut == Cut(at(3), inclusive=True)


def test_descending_cut_uses_the_latest_boundary_across_sources() -> None:
    newest = _rows(9, 8, 7)  # limit 2 overflows; first excluded starts at 7
    other = _rows(6, 5)  # complete
    kept, cut = cut_window([newest, other], [2, 5], _key, ascending=False)
    assert _names(kept) == ["e9", "e8"]
    assert cut == Cut(at(7), inclusive=True)


def test_earliest_cut_wins_across_sources_in_ascending_order() -> None:
    first = _rows(1, 2, 3)  # cut at 2
    second = _rows(4, 5, 6)  # cut at 6
    kept, cut = cut_window([first, second], [1, 2], _key, ascending=True)
    assert _names(kept) == ["e1"]
    assert cut == Cut(at(2), inclusive=True)


def test_rows_tied_at_the_cut_wait_for_the_next_window() -> None:
    overflowing = _rows(1, 2, 3)  # cut at 3
    tied_elsewhere = [Row("x", at(3))]  # complete, same start as the cut
    kept, cut = cut_window(
        [overflowing, tied_elsewhere], [2, 5], _key, ascending=True
    )
    assert _names(kept) == ["e1", "e2"]
    assert cut == Cut(at(3), inclusive=True)


def test_tie_group_larger_than_the_limit_fills_the_window_and_resumes_after() -> None:
    tied = [Row("a", at(5)), Row("b", at(5)), Row("c", at(5))]
    kept, cut = cut_window([tied], [2], _key, ascending=True)
    assert _names(kept) == ["a", "b", "c"]
    assert cut == Cut(at(5), inclusive=False)


def _fetch(data: list[Row], lower: Bound | None, limit: int) -> list[Row]:
    """Stand-in for the database: one ascending range, limit + 1 rows."""
    rows = [
        row
        for row in data
        if lower is None
        or row.start_at > lower.value
        or (lower.inclusive and row.start_at == lower.value)
    ]
    return rows[: limit + 1]


def test_walking_windows_visits_every_row_exactly_once() -> None:
    data = [
        Row(f"r{index}", at(hours))
        for index, hours in enumerate([1, 2, 2, 2, 3, 4, 4, 5, 6, 6, 7])
    ]
    limit = 3
    seen: list[str] = []
    cursor: Cursor | None = None
    for _ in range(50):
        (scan,) = public_scans(
            "upcoming",
            NOW - timedelta(days=1),
            None,
            None,
            cursor,
            status_limit=limit,
            recent_limit=limit,
        )
        window = _fetch(data, scan.lower, limit)
        kept, cut = cut_window([window], [limit], _key, ascending=True)
        seen.extend(_names(kept))
        if cut.boundary is None:
            break
        cursor = Cursor("upcoming", None, cut.boundary, cut.inclusive)
    assert sorted(seen) == sorted(_names(data))
    assert len(seen) == len(set(seen))


# --- cursor tokens ---------------------------------------------------------


def test_cursor_round_trips() -> None:
    token = cursor_after("upcoming", None, Cut(at(3), inclusive=False))
    assert resolve_cursor(token, "upcoming", None) == Cursor(
        "upcoming", None, at(3), False
    )


def test_complete_window_has_no_cursor() -> None:
    assert cursor_after("past", None, Cut()) is None


def test_cursor_for_another_query_is_rejected() -> None:
    token = cursor_after("past", None, Cut(at(3), True))
    with pytest.raises(InvalidCursorError):
        resolve_cursor(token, "upcoming", None)
    with pytest.raises(InvalidCursorError):
        resolve_cursor(token, "past", "9f0c2a51-7d3e-4b1a-8c55-1f2e3d4c5b6a")


@pytest.mark.parametrize(
    "token",
    ["not base64!!", "bm90IGpzb24", "eyJwIjoidXBjb21pbmcifQ", "WzEsMiwzXQ"],
)
def test_malformed_cursor_is_rejected(token: str) -> None:
    with pytest.raises(InvalidCursorError):
        resolve_cursor(token, "upcoming", None)


def test_invalid_cursor_is_a_422_validation_error() -> None:
    assert InvalidCursorError.status == 422
    assert InvalidCursorError.code == "VALIDATION_ERROR"
