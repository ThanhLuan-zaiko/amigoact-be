"""Unit tests for the public events:feed publishers and the brief ranking."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from activities.events import WsActivityEvents
from core.ids import uuid7
from core.realtime import Channel, parse_channel
from registrations.brief_service import RegistrationBriefService
from registrations.seat_events import WsSeatEvents

FEED = "events:feed"


class FakeManager:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    def schedule_publish(self, channel, payload=None):  # noqa: ANN001, ANN202
        self.sent.append((channel, payload))
        return True

    def feed(self) -> list[dict]:
        return [payload for channel, payload in self.sent if channel == FEED]


def _publish(action: str, status: str) -> FakeManager:
    manager = FakeManager()
    org, activity, actor = uuid7(), uuid7(), uuid7()
    WsActivityEvents(manager).activity_changed(org, action, activity, actor, status)
    return manager


def test_draft_changes_stay_off_the_public_feed() -> None:
    manager = _publish("updated", "draft")
    assert manager.feed() == []
    assert len(manager.sent) == 1  # only the private activities:{org} hint


def test_published_change_is_mirrored_as_updated() -> None:
    manager = _publish("updated", "published")
    assert [payload["action"] for payload in manager.feed()] == ["updated"]


def test_cancel_and_delete_remove_the_card() -> None:
    assert [p["action"] for p in _publish("cancelled", "cancelled").feed()] == ["removed"]
    assert [p["action"] for p in _publish("deleted", "published").feed()] == ["removed"]


def test_slot_changes_never_publish_publicly() -> None:
    assert _publish("slot_created", "published").feed() == []


def test_public_payload_carries_ids_only() -> None:
    manager = _publish("updated", "ongoing")
    (payload,) = manager.feed()
    assert set(payload) == {"action", "activity_id", "org_id"}


def test_seat_hint_uses_the_same_public_channel() -> None:
    manager = FakeManager()
    WsSeatEvents(manager).seats_changed(uuid7(), uuid7())
    (channel, payload), = manager.sent
    assert channel == FEED
    assert payload["action"] == "seats"


def test_missing_registry_is_a_silent_no_op() -> None:
    WsActivityEvents(None).activity_changed(uuid7(), "updated", uuid7(), uuid7(), "published")
    WsSeatEvents(None).seats_changed(uuid7(), uuid7())


def test_events_channel_is_public_and_literal() -> None:
    assert parse_channel(FEED) == Channel(kind="events", subject=None)
    assert parse_channel(f"events:{uuid7()}") is None
    assert parse_channel("activities:feed") is None


class FakeBriefRows:
    def __init__(self, rows) -> None:  # noqa: ANN001
        self.rows = rows

    def student_rows(self, student_id, limit=500):  # noqa: ANN001, ANN202
        return self.rows


def _row(activity, status: str, days_ago: int):  # noqa: ANN001, ANN202
    return SimpleNamespace(
        activity_id=activity,
        registration_id=uuid7(),
        status=status,
        registered_at=datetime(2026, 10, 25) - timedelta(days=days_ago),
    )


def test_attended_beats_a_newer_cancelled_attempt() -> None:
    activity = uuid7()
    rows = [_row(activity, "cancelled", 1), _row(activity, "attended", 30)]
    (brief,) = RegistrationBriefService(FakeBriefRows(rows)).briefs_for(uuid7())
    assert brief.status == "attended"


def test_newest_wins_when_statuses_tie() -> None:
    activity = uuid7()
    older = _row(activity, "pending", 10)
    newer = _row(activity, "pending", 1)
    (brief,) = RegistrationBriefService(FakeBriefRows([older, newer])).briefs_for(uuid7())
    assert brief.registration_id == newer.registration_id


def test_one_brief_per_activity() -> None:
    first, second = uuid7(), uuid7()
    rows = [_row(first, "approved", 2), _row(second, "rejected", 3), _row(first, "cancelled", 9)]
    briefs = RegistrationBriefService(FakeBriefRows(rows)).briefs_for(uuid7())
    assert sorted((b.activity_id, b.status) for b in briefs) == sorted(
        [(first, "approved"), (second, "rejected")]
    )
