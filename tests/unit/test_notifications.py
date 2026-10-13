"""Unit tests for NotificationService (in-memory store)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
import uuid_utils

from core.exceptions import ForbiddenError, NotFoundError
from notifications.interfaces import NotificationStore
from notifications.service import NotificationService


def _uid() -> UUID:
    return UUID(str(uuid_utils.uuid7()))


class FakeStore(NotificationStore):
    def __init__(self) -> None:
        self.rows: dict[UUID, SimpleNamespace] = {}
        self.feeds: dict[UUID, list[SimpleNamespace]] = {}

    def create(self, notification_id, user_id, type, title, body, data_json, now):  # noqa: ANN001, ANN202, A002
        row = SimpleNamespace(
            notification_id=notification_id, user_id=user_id, type=type,
            title=title, body=body, data_json=data_json, status="unread",
            read_at=None, created_at=now,
        )
        self.rows[notification_id] = row
        feed = SimpleNamespace(
            user_id=user_id, created_at=now,
            notification_id=notification_id, title=title, status="unread",
        )
        self.feeds.setdefault(user_id, []).insert(0, feed)
        return row

    def get(self, notification_id):  # noqa: ANN001, ANN202
        return self.rows.get(notification_id)

    def list_by_user(self, user_id):  # noqa: ANN001, ANN202
        return list(self.feeds.get(user_id, []))

    def mark_read(self, row, now):  # noqa: ANN001, ANN202
        row.status = "read"
        row.read_at = now
        for feed in self.feeds.get(row.user_id, []):
            if feed.notification_id == row.notification_id:
                feed.status = "read"

    def mark_all_read(self, user_id, now):  # noqa: ANN001, ANN202
        marked = 0
        for feed in self.feeds.get(user_id, []):
            if feed.status != "unread":
                continue
            feed.status = "read"
            row = self.rows[feed.notification_id]
            row.status = "read"
            row.read_at = now
            marked += 1
        return marked


def _service() -> tuple[NotificationService, FakeStore]:
    store = FakeStore()
    return NotificationService(store), store


def test_notify_persists_row_and_feed() -> None:
    service, store = _service()
    user = _uid()
    service.notify(user, "membership", "Hello", "Body")
    assert len(store.rows) == 1
    assert len(store.feeds[user]) == 1
    row = next(iter(store.rows.values()))
    assert row.status == "unread"


def test_list_mine_paginates_and_counts_unread() -> None:
    service, _ = _service()
    user, other = _uid(), _uid()
    for index in range(3):
        service.notify(user, "system", f"n{index}")
    service.notify(other, "system", "alien")
    items, total, unread = service.list_mine(user, limit=2, offset=0)
    assert total == 3 and unread == 3 and len(items) == 2
    items, total, unread = service.list_mine(user, limit=2, offset=2)
    assert len(items) == 1


def test_mark_read_flips_status_once() -> None:
    service, store = _service()
    user = _uid()
    service.notify(user, "system", "t")
    nid = next(iter(store.rows))
    first = service.mark_read(user, nid)
    second = service.mark_read(user, nid)
    assert first.status == "read" and first.read_at is not None
    assert second.read_at == first.read_at
    _, _, unread = service.list_mine(user)
    assert unread == 0


def test_list_mine_returns_parsed_deep_link_data() -> None:
    service, store = _service()
    user = _uid()
    service.notify(
        user, "announcement", "t", "b",
        data_json='{"org_id": "abc", "post_id": "def"}',
    )
    service.notify(user, "system", "corrupt", data_json="not json")
    items, _, _ = service.list_mine(user)
    assert items[0].data is None  # corrupt payload never breaks the inbox
    assert items[1].data == {"org_id": "abc", "post_id": "def"}
    nid = items[1].id
    assert service.mark_read(user, nid).data == {
        "org_id": "abc", "post_id": "def"
    }


def test_mark_all_read_clears_badge_and_is_idempotent() -> None:
    service, _ = _service()
    user, other = _uid(), _uid()
    for index in range(3):
        service.notify(user, "system", f"n{index}")
    service.notify(other, "system", "alien")
    assert service.mark_all_read(user) == 3
    _, _, unread = service.list_mine(user)
    assert unread == 0
    _, _, other_unread = service.list_mine(other)
    assert other_unread == 1
    assert service.mark_all_read(user) == 0


def test_mark_read_rejects_foreign_and_missing() -> None:
    service, store = _service()
    owner, stranger = _uid(), _uid()
    service.notify(owner, "system", "t")
    nid = next(iter(store.rows))
    with pytest.raises(ForbiddenError):
        service.mark_read(stranger, nid)
    with pytest.raises(NotFoundError):
        service.mark_read(owner, _uid())
