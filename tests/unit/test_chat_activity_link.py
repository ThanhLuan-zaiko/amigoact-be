"""Unit tests: deleting an event freezes or purges its chat rooms."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from chat.activity_link import ChatActivityLink, month_buckets
from core.exceptions import ActivityDeletedError, ChannelArchivedError
from tests.unit.chat_fakes import FakeChatEvents, make_attachments
from tests.unit.test_chat_threads import _member, _thread, _world
from tests.unit.workspace_fakes import NOW, _uid


class FakePurge:
    """Records every purge call; returns no attachment blobs."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def purge_room(self, room_id, buckets):  # noqa: ANN001, ANN201
        self.calls.append((room_id, list(buckets)))
        return []


def _event_world():  # noqa: ANN202
    (_s, _r, threads, rooms, _c, channels, _o,
     members, users, _a, org_id, owner, acts,) = _world()
    activity_id = _uid()
    acts.add(activity_id, org_id, "Beach cleanup")
    thread = _thread(
        threads, org_id, org_id, owner, activity_id=activity_id
    )
    member = _member(members, users, org_id)
    return threads, rooms, channels, acts, org_id, owner, member, (
        activity_id, thread.channel_id
    )


def test_trashed_event_freezes_thread_and_room() -> None:
    threads, rooms, _ch, acts, org_id, owner, member, ids = _event_world()
    activity_id, thread_id = ids
    sent = rooms.send_message(thread_id, member, "before trash")
    acts.activities[activity_id].deleted_at = NOW

    for room_id in (thread_id, activity_id):
        with pytest.raises(ActivityDeletedError):
            rooms.send_message(room_id, member, "after trash")
    with pytest.raises(ActivityDeletedError):
        rooms.edit_message(thread_id, member, sent.message_id, "edited")
    with pytest.raises(ActivityDeletedError):
        rooms.toggle_reaction(thread_id, member, sent.message_id, "\U0001F44D")
    # History stays readable while the event sits in the trash.
    page = rooms.list_messages(thread_id, member)
    assert [m.message_id for m in page.items] == [sent.message_id]
    listed = threads.list_room_threads(org_id, org_id, owner)
    assert [t.activity_deleted for t in listed] == [True]


def test_restored_event_unfreezes_thread() -> None:
    threads, rooms, _ch, acts, org_id, owner, member, ids = _event_world()
    activity_id, thread_id = ids
    acts.activities[activity_id].deleted_at = NOW
    acts.activities[activity_id].deleted_at = None
    rooms.send_message(thread_id, member, "back again")
    listed = threads.list_room_threads(org_id, org_id, owner)
    assert [t.activity_deleted for t in listed] == [False]


def test_new_thread_on_trashed_event_is_refused() -> None:
    threads, _r, _ch, acts, org_id, owner, _m, ids = _event_world()
    acts.activities[ids[0]].deleted_at = NOW
    with pytest.raises(ActivityDeletedError):
        _thread(
            threads, org_id, org_id, owner,
            name="late-thread", activity_id=ids[0],
        )


def test_purge_wipes_room_and_archives_linked_threads() -> None:
    threads, rooms, channels, acts, org_id, owner, member, ids = (
        _event_world()
    )
    activity_id, thread_id = ids
    plain = _thread(threads, org_id, org_id, owner, name="plain-talk")
    purge, events = FakePurge(), FakeChatEvents()
    link = ChatActivityLink(purge, channels, events, make_attachments())
    created = datetime(2025, 11, 3, tzinfo=timezone.utc)

    link.activity_purged(org_id, activity_id, created, owner)
    del acts.activities[activity_id]

    room_id, buckets = purge.calls[0]
    assert room_id == activity_id
    assert buckets[:3] == ["202511", "202512", "202601"]
    assert channels.get_channel(thread_id).archived_at is not None
    assert channels.get_channel(plain.channel_id).archived_at is None
    assert ("room.deleted", activity_id, org_id, ()) in events.inbox
    with pytest.raises((ChannelArchivedError, ActivityDeletedError)):
        rooms.send_message(thread_id, owner, "gone")
    # Managers still read the archived thread, now marked as deleted.
    listed = {
        t.channel_id: t for t in threads.list_room_threads(
            org_id, org_id, owner
        )
    }
    assert listed[thread_id].activity_deleted is True
    assert listed[thread_id].activity_title is None
    # Members no longer see the archived thread at all.
    visible = threads.list_room_threads(org_id, org_id, member)
    assert thread_id not in {t.channel_id for t in visible}


def test_month_buckets_spans_year_boundary() -> None:
    start = datetime(2025, 12, 31, tzinfo=timezone.utc)
    end = datetime(2026, 2, 1, tzinfo=timezone.utc)
    assert month_buckets(start, end) == ["202512", "202601", "202602"]
    assert month_buckets(None, end) == ["202602"]
