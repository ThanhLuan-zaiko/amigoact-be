"""Mine-listing search, filter, sort and paging over org snapshots.

Mine reads stay on the single members_by_user partition, so text, status
and paging filters run in memory here. No new query table, no ALLOW
FILTERING; revisit only if per-user org counts ever outgrow one page
(see docs/ORGS.md).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orgs.service import OrgSnapshot

_BUCKET_ORDER = ("active", "pending")


def fold_search_text(value: str) -> str:
    """Fold Vietnamese text so search ignores case and diacritics."""
    lowered = value.lower().replace("\u0111", "d")
    decomposed = unicodedata.normalize("NFD", lowered)
    return "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    ).strip()


def status_bucket(legal_status: str, status: str) -> str:
    """Pending legal review wins; odd values fall through as their own chip."""
    if legal_status == "pending":
        return "pending"
    return status or "active"


@dataclass(frozen=True)
class OrgListResult:
    """One filtered page plus totals for the pager and status chips."""

    items: list[OrgSnapshot]
    total: int
    counts: list[tuple[str, int]] = field(default_factory=list)


def _bucket_counts(snapshots: list[OrgSnapshot]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for snapshot in snapshots:
        key = status_bucket(snapshot.legal_status, snapshot.status)
        counts[key] = counts.get(key, 0) + 1
    order = {key: index for index, key in enumerate(_BUCKET_ORDER)}
    return sorted(
        counts.items(),
        key=lambda item: (order.get(item[0], len(order)), item[0]),
    )


def paginate_mine(
    snapshots: list[OrgSnapshot],
    *,
    q: str | None = None,
    status: str | None = None,
    sort: str = "newest",
    limit: int = 20,
    offset: int = 0,
) -> OrgListResult:
    """Filter by text/status, sort, then slice one page with totals."""
    term = fold_search_text(q) if q else ""
    searched = (
        snapshots
        if not term
        else [
            snapshot
            for snapshot in snapshots
            if term in fold_search_text(f"{snapshot.name} {snapshot.slug}")
        ]
    )
    counts = _bucket_counts(searched)
    if status is None or status == "all":
        filtered = searched
    else:
        filtered = [
            snapshot
            for snapshot in searched
            if status_bucket(snapshot.legal_status, snapshot.status) == status
        ]
    if sort == "name":
        ordered = sorted(filtered, key=lambda item: fold_search_text(item.name))
    elif sort == "members":
        ordered = sorted(filtered, key=lambda item: item.member_count, reverse=True)
    else:
        ordered = sorted(filtered, key=lambda item: item.created_at, reverse=True)
    return OrgListResult(
        items=ordered[offset : offset + limit],
        total=len(filtered),
        counts=counts,
    )
