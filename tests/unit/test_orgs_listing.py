"""Unit tests for mine-listing search, filter, sort and paging (no I/O)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from core.ids import uuid7
from orgs.listing import fold_search_text, paginate_mine, status_bucket
from orgs.service import OrgSnapshot


def _snap(
    name: str,
    slug: str,
    *,
    kind: str = "club",
    legal_status: str = "none",
    status: str = "active",
    members: int = 1,
    age_days: int = 0,
) -> OrgSnapshot:
    now = datetime.now(timezone.utc) - timedelta(days=age_days)
    return OrgSnapshot(
        id=uuid7(),
        owner_id=UUID(int=0),
        name=name,
        slug=slug,
        description="",
        kind=kind,
        tax_code=None,
        legal_rep_name=None,
        legal_rep_id=None,
        legal_rep_position=None,
        legal_status=legal_status,
        status=status,
        deleted_at=None,
        member_count=members,
        created_at=now,
    )


def test_fold_ignores_case_and_vietnamese_diacritics() -> None:
    assert fold_search_text("Hà Nội") == "ha noi"
    assert fold_search_text("ĐÀ NẴNG") == "da nang"
    assert fold_search_text("  Club  ") == "club"


def test_pending_legal_review_wins_status_bucket() -> None:
    assert status_bucket("pending", "active") == "pending"
    assert status_bucket("none", "active") == "active"
    assert status_bucket("none", "") == "active"


def test_q_matches_name_and_slug_without_diacritics() -> None:
    rows = [_snap("Hội An", "hoi-an"), _snap("Da Nang", "da-nang")]
    assert [o.slug for o in paginate_mine(rows, q="hoi an").items] == ["hoi-an"]
    assert [o.slug for o in paginate_mine(rows, q="DA-NANG").items] == ["da-nang"]
    assert paginate_mine(rows, q="hue").total == 0


def test_status_filter_uses_buckets_and_counts_stay_prefilter() -> None:
    rows = [
        _snap("Biz", "biz", kind="business", legal_status="pending"),
        _snap("Club", "club"),
    ]
    page = paginate_mine(rows, status="pending")
    assert [o.slug for o in page.items] == ["biz"]
    assert page.total == 1
    assert page.counts == [("active", 1), ("pending", 1)]
    assert paginate_mine(rows, status="nope").items == []


def test_name_sort_folds_diacritics_like_vietnamese_order() -> None:
    rows = [_snap("Hội An", "hoi-an"), _snap("Da Nang", "da-nang"), _snap("Hue", "hue")]
    assert [o.slug for o in paginate_mine(rows, sort="name").items] == [
        "da-nang",
        "hoi-an",
        "hue",
    ]


def test_sort_orders_and_paging_keeps_total() -> None:
    rows = [
        _snap("Charlie", "c", members=1, age_days=0),
        _snap("Alpha", "a", members=3, age_days=2),
        _snap("Bravo", "b", members=2, age_days=1),
    ]
    assert [o.slug for o in paginate_mine(rows).items] == ["c", "b", "a"]
    assert [o.slug for o in paginate_mine(rows, sort="name").items] == ["a", "b", "c"]
    assert [o.slug for o in paginate_mine(rows, sort="members").items] == ["a", "b", "c"]
    first = paginate_mine(rows, sort="name", limit=2, offset=0)
    assert [o.slug for o in first.items] == ["a", "b"]
    assert first.total == 3
    second = paginate_mine(rows, sort="name", limit=2, offset=2)
    assert [o.slug for o in second.items] == ["c"]
    assert second.total == 3
    assert paginate_mine(rows, limit=2, offset=9).items == []
