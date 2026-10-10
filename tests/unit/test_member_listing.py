"""Unit tests for member roster search/filter/sort/paginate."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import uuid_utils

from orgs.member_listing import MemberSnapshot, paginate_members


def _uid() -> UUID:
    return UUID(str(uuid_utils.uuid7()))


def _snap(
    name: str,
    status: str = "active",
    role: str = "member",
    age_minutes: int = 0,
    email: str | None = "x@example.com",
) -> MemberSnapshot:
    return MemberSnapshot(
        org_id=_uid(),
        user_id=_uid(),
        full_name=name,
        email=email,
        role=role,
        status=status,
        joined_at=datetime.now(timezone.utc) - timedelta(minutes=age_minutes),
    )


def test_search_folds_accents_and_matches_email() -> None:
    items = [
        _snap("Nguy\u1ec5n V\u0103n H\u1ed9i"),
        _snap("Tr\u1ea7n Th\u1ecb Mai"),
        _snap("Other", email="z@example.com"),
    ]
    result = paginate_members(items, q="h\u1ed9i")
    assert {item.full_name for item in result.items} == {
        "Nguy\u1ec5n V\u0103n H\u1ed9i"
    }
    result = paginate_members(items, q="z@example")
    assert {item.full_name for item in result.items} == {"Other"}


def test_status_filter_and_bucket_counts() -> None:
    items = [
        _snap("A", "active"),
        _snap("B", "active"),
        _snap("C", "invited"),
        _snap("D", "left"),
    ]
    result = paginate_members(items, status="active")
    assert result.total == 2
    counts = dict(result.counts)
    assert counts == {"active": 2, "invited": 1, "left": 1}
    # Counts respect the search scope but ignore the status filter itself.
    searched = paginate_members(items, q="no-match", status="active")
    assert searched.total == 0
    assert searched.counts == []


def test_sort_newest_name_and_role() -> None:
    items = [
        _snap("Charlie", role="member", age_minutes=10),
        _snap("Alice", role="owner", age_minutes=30),
        _snap("Bob", role="admin", age_minutes=20),
    ]
    newest = paginate_members(items, sort="newest")
    assert [i.full_name for i in newest.items] == ["Charlie", "Bob", "Alice"]
    named = paginate_members(items, sort="name")
    assert [i.full_name for i in named.items] == ["Alice", "Bob", "Charlie"]
    by_role = paginate_members(items, sort="role")
    assert [i.role for i in by_role.items] == ["owner", "admin", "member"]


def test_pagination_slices_and_reports_total() -> None:
    items = [_snap(f"User {index:02d}") for index in range(8)]
    first = paginate_members(items, sort="name", limit=3, offset=0)
    assert [i.full_name for i in first.items] == ["User 00", "User 01", "User 02"]
    assert first.total == 8
    last = paginate_members(items, sort="name", limit=3, offset=6)
    assert [i.full_name for i in last.items] == ["User 06", "User 07"]
    empty = paginate_members(items, sort="name", limit=3, offset=9)
    assert empty.items == [] and empty.total == 8
