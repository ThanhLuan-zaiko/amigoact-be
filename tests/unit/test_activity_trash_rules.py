from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from src.activities.listing import org_filter_query
from src.activities.trash_rules import (
    TRASH_DAYS,
    may_purge,
    may_restore,
    purge_at,
    trash_expired,
)
from src.models.activities import Activity
from src.organizations.access import Access

DELETED = datetime(2026, 11, 1, tzinfo=UTC)


def test_trash_keeps_an_activity_for_thirty_days() -> None:
    assert TRASH_DAYS == 30
    assert purge_at(DELETED) == DELETED + timedelta(days=30)
    assert trash_expired(DELETED, DELETED + timedelta(days=29)) is False
    assert trash_expired(DELETED, DELETED + timedelta(days=30)) is True


def test_owners_and_admins_restore_only_the_owner_purges() -> None:
    owner = Access(status="active", role="owner")
    admin = Access(status="active", role="admin")
    member = Access(status="active", role="member")
    outsider = Access(status=None, role=None)
    assert [may_restore(a) for a in (owner, admin, member, outsider)] == [
        True,
        True,
        False,
        False,
    ]
    assert [may_purge(a) for a in (owner, admin, member, outsider)] == [
        True,
        False,
        False,
        False,
    ]


def _sql(view: str | None) -> str:
    query = org_filter_query(select(Activity), view)  # type: ignore[arg-type]
    compiled = query.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    return str(compiled)


def test_main_list_leaves_drafts_out() -> None:
    assert "activities.status != 'draft'" in _sql(None)


@pytest.mark.parametrize(
    ("view", "status"),
    [("draft", "draft"), ("completed", "completed"), ("cancelled", "cancelled")],
)
def test_each_tab_shows_one_status(view: str, status: str) -> None:
    assert f"activities.status = '{status}'" in _sql(view)


def test_upcoming_is_published_not_started_and_soonest_first() -> None:
    sql = _sql("upcoming")
    assert "activities.status = 'published'" in sql
    assert "activities.start_at > now()" in sql
    assert sql.rstrip().endswith("ORDER BY activities.start_at, activities.id")
