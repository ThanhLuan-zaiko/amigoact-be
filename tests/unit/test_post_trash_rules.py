from datetime import UTC, datetime, timedelta

from src.organizations.access import Access
from src.organizations.permissions import ALL, DEFAULT_ADMIN
from src.posts.rules import (
    COMMENT_EDIT_MINUTES,
    TRASH_DAYS,
    comment_editable,
    may_purge,
    may_restore,
    purge_at,
    trash_expired,
)

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def test_purge_at_is_the_keep_period_after_the_delete() -> None:
    assert purge_at(NOW) == NOW + timedelta(days=TRASH_DAYS)
    assert TRASH_DAYS == 30


def test_trash_expires_exactly_at_the_end_of_the_keep_period() -> None:
    assert trash_expired(NOW - timedelta(days=TRASH_DAYS), NOW) is True
    assert trash_expired(NOW - timedelta(days=TRASH_DAYS, seconds=-1), NOW) is False


def test_comment_is_editable_only_inside_the_window() -> None:
    window = timedelta(minutes=COMMENT_EDIT_MINUTES)
    assert comment_editable(NOW - window + timedelta(seconds=1), NOW) is True
    assert comment_editable(NOW - window, NOW) is False


def test_owners_and_admins_restore_but_only_owners_purge() -> None:
    owner = Access(status="active", role="owner", permissions=ALL)
    admin = Access(status="active", role="admin", permissions=DEFAULT_ADMIN)
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


def test_a_suspended_owner_cannot_purge() -> None:
    assert may_purge(Access(status="suspended", role="owner", permissions=ALL)) is False
