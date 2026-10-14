"""Mine-listing and public-directory search, filter, sort and paging.

Mine reads stay on the single members_by_user partition, so text, status
and paging filters run in memory here. Public reads merge the small
kind-partitioned organizations_public feed and do the same. No ALLOW
FILTERING; revisit only if org counts ever outgrow one page
(see docs/ORGS.md).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from orgs.interfaces import OrgActivityBrief, OrgPostBrief
    from orgs.service import OrgSnapshot

_BUCKET_ORDER = ("active", "pending")
_PUBLIC_KIND_ORDER = ("organization", "club", "group", "business")


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


@dataclass(frozen=True)
class PublicOrgSnapshot:
    """Guest-facing org card; no legal, contact or owner-id fields.

    owner_name/owner_avatar_url are public display identity (like a post's
    author), never the raw owner_id or any legal-rep data.
    """

    id: UUID
    name: str
    slug: str
    description: str
    kind: str
    member_count: int
    join_policy: str
    city: str | None
    country: str | None
    verified_at: datetime | None
    logo_url: str | None
    cover_url: str | None
    created_at: datetime
    owner_name: str | None = None
    owner_avatar_url: str | None = None


@dataclass(frozen=True)
class PublicOrgDetail:
    """Full guest-facing profile; owner and legal-rep fields stay out."""

    id: UUID
    name: str
    slug: str
    description: str
    kind: str
    member_count: int
    join_policy: str
    email: str | None
    phone: str | None
    website: str | None
    address: str | None
    city: str | None
    country: str | None
    legal_status: str
    legal_name: str | None
    license_number: str | None
    tax_code: str | None
    verified_at: datetime | None
    logo_url: str | None
    cover_url: str | None
    gallery: list[str]
    activity_count: int
    activities: list[OrgActivityBrief]
    announcement_count: int
    announcements: list[OrgPostBrief]
    created_at: datetime


@dataclass(frozen=True)
class PublicOrgListResult:
    """One public-directory page plus kind chips for the filter row."""

    items: list[PublicOrgSnapshot]
    total: int
    counts: list[tuple[str, int]] = field(default_factory=list)


def _kind_counts(
    snapshots: list[PublicOrgSnapshot],
) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for snapshot in snapshots:
        counts[snapshot.kind] = counts.get(snapshot.kind, 0) + 1
    order = {key: index for index, key in enumerate(_PUBLIC_KIND_ORDER)}
    return sorted(
        counts.items(),
        key=lambda item: (order.get(item[0], len(order)), item[0]),
    )


def paginate_public(
    snapshots: list[PublicOrgSnapshot],
    *,
    q: str | None = None,
    kind: str | None = None,
    sort: str = "newest",
    limit: int = 24,
    offset: int = 0,
) -> PublicOrgListResult:
    """Filter by text/kind, sort, then slice one page with kind counts."""
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
    counts = _kind_counts(searched)
    if kind is None or kind == "all":
        filtered = searched
    else:
        filtered = [snapshot for snapshot in searched if snapshot.kind == kind]
    if sort == "name":
        ordered = sorted(filtered, key=lambda item: fold_search_text(item.name))
    elif sort == "members":
        ordered = sorted(
            filtered,
            key=lambda item: (item.member_count, item.created_at),
            reverse=True,
        )
    else:
        ordered = sorted(filtered, key=lambda item: item.created_at, reverse=True)
    return PublicOrgListResult(
        items=ordered[offset : offset + limit],
        total=len(filtered),
        counts=counts,
    )
