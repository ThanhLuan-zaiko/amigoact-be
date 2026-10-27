"""Search rules for the public browse feed.

Phase and registration-window rules live in core.event_phase and are
re-exported here, so the feed keeps a single import path.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from core.event_phase import (
    DEFAULT_DURATION,
    classify_phase,
    is_registration_open,
    utc_naive,
)
from orgs.listing import fold_search_text

__all__ = [
    "DEFAULT_DURATION",
    "PHASES",
    "classify_phase",
    "is_registration_open",
    "matches_query",
    "utc_naive",
]

PHASES: Final = ("upcoming", "ongoing", "past")


def matches_query(folded_term: str, parts: Iterable[str | None]) -> bool:
    """Diacritic-insensitive substring match over several text fields.

    The caller folds the term once with fold_search_text.
    """
    haystack = fold_search_text(" ".join(part for part in parts if part))
    return folded_term in haystack
