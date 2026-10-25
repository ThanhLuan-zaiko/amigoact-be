"""Facet counts for the browse feed: pure helpers over activity rows.

A facet counts the rows it is handed; the service decides which filters
those rows already passed. Faceted search needs every facet to skip its
own filter, so the caller picks the rows per facet.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from activities.model import Activity
from activities.model import tag_slug as tag_key
from orgs.listing import fold_search_text

# Tags form a long tail; the dropdown lists the most used ones in scope.
TAG_FACET_LIMIT = 50


@dataclass(frozen=True)
class CategoryCount:
    category_id: UUID
    name: str
    count: int


@dataclass(frozen=True)
class TagCount:
    slug: str
    name: str
    count: int


def tag_slugs(row: Activity) -> set[str]:
    """Normalized tag keys carried by one activity."""
    return {tag_key(name) for name in row.tag_names or []}


def _ranked(counts: dict) -> list:
    """Most populated first, then by key so the order is stable."""
    return sorted(counts, key=lambda key: (-counts[key], key))


def city_counts(rows: Iterable[Activity]) -> list[tuple[str, int]]:
    labels: dict[str, str] = {}
    counts: dict[str, int] = {}
    for row in rows:
        city = (row.city or "").strip()
        if not city:
            continue
        key = fold_search_text(city)
        labels.setdefault(key, city)
        counts[key] = counts.get(key, 0) + 1
    return [(labels[key], counts[key]) for key in _ranked(counts)]


def status_counts(statuses: Iterable[str]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for status in statuses:
        counts[status] = counts.get(status, 0) + 1
    return [(status, counts[status]) for status in _ranked(counts)]


def category_counts(
    rows: Iterable[Activity], names: dict[UUID, str]
) -> list[CategoryCount]:
    """Only categories present in the catalog get a row; the rest drop out."""
    counts: dict[UUID, int] = {}
    for row in rows:
        if row.category_id in names:
            counts[row.category_id] = counts.get(row.category_id, 0) + 1
    ordered = sorted(counts, key=lambda cid: (-counts[cid], names[cid]))
    return [CategoryCount(cid, names[cid], counts[cid]) for cid in ordered]


def tag_counts(rows: Iterable[Activity]) -> list[TagCount]:
    """Count each tag once per activity; display the first spelling seen."""
    labels: dict[str, str] = {}
    counts: dict[str, int] = {}
    for row in rows:
        for name in row.tag_names or []:
            key = tag_key(name)
            if not key:
                continue
            labels.setdefault(key, name)
        for key in tag_slugs(row) - {""}:
            counts[key] = counts.get(key, 0) + 1
    return [
        TagCount(key, labels[key], counts[key])
        for key in _ranked(counts)[:TAG_FACET_LIMIT]
    ]
