"""Member roster snapshots plus search, filter, sort and paging.

Members live on a single `organization_members` partition, so text,
status and paging filters run in memory here - same rationale as
`listing.py` for the mine read. No new query table, no ALLOW FILTERING.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from orgs.listing import fold_search_text

_MEMBER_ORDER = ("active", "invited", "suspended", "left")


def _role_rank(roles: list[str]) -> int:
    """Display ordering: owner, admin, customs, plain member."""
    if "owner" in roles:
        return 0
    if "admin" in roles:
        return 1
    if roles:
        return 2
    return 3


@dataclass(frozen=True)
class MemberSnapshot:
    """One roster row with display fields resolved."""

    org_id: UUID
    user_id: UUID
    full_name: str
    email: str | None
    roles: list[str]
    status: str
    invited_by: UUID | None
    invited_by_name: str | None
    joined_at: datetime


@dataclass(frozen=True)
class MembershipSnapshot:
    """One caller membership link with org display fields."""

    org_id: UUID
    org_name: str
    org_slug: str
    roles: list[str]
    status: str
    invited_by_name: str | None
    joined_at: datetime


@dataclass(frozen=True)
class SkillMatch:
    """One org member holding a searched skill (coordinator matching)."""

    user_id: UUID
    full_name: str
    level: int


@dataclass(frozen=True)
class MemberPage:
    """Roster page plus the caller's effective role and permissions."""

    items: list[MemberSnapshot]
    total: int
    counts: list[tuple[str, int]] = field(default_factory=list)
    viewer_role: str = "member"
    viewer_permissions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MemberListResult:
    """One filtered page plus totals for the pager and status chips."""

    items: list[MemberSnapshot]
    total: int
    counts: list[tuple[str, int]] = field(default_factory=list)


def _bucket_counts(snapshots: list[MemberSnapshot]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for snapshot in snapshots:
        key = snapshot.status or "active"
        counts[key] = counts.get(key, 0) + 1
    order = {key: index for index, key in enumerate(_MEMBER_ORDER)}
    return sorted(
        counts.items(),
        key=lambda item: (order.get(item[0], len(order)), item[0]),
    )


def paginate_members(
    snapshots: list[MemberSnapshot],
    *,
    q: str | None = None,
    status: str | None = None,
    sort: str = "newest",
    limit: int = 20,
    offset: int = 0,
) -> MemberListResult:
    """Filter by text/status, sort, then slice one page with totals."""
    term = fold_search_text(q) if q else ""
    searched = (
        snapshots
        if not term
        else [
            snapshot
            for snapshot in snapshots
            if term
            in fold_search_text(
                f"{snapshot.full_name} {snapshot.email or ''}"
            )
        ]
    )
    counts = _bucket_counts(searched)
    if status is None or status == "all":
        filtered = searched
    else:
        filtered = [
            snapshot for snapshot in searched if snapshot.status == status
        ]
    if sort == "name":
        ordered = sorted(
            filtered, key=lambda item: fold_search_text(item.full_name)
        )
    elif sort == "role":
        ordered = sorted(
            filtered,
            key=lambda item: (
                _role_rank(item.roles),
                fold_search_text(item.full_name),
            ),
        )
    else:
        ordered = sorted(
            filtered, key=lambda item: item.joined_at, reverse=True
        )
    return MemberListResult(
        items=ordered[offset : offset + limit],
        total=len(filtered),
        counts=counts,
    )
