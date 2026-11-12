"""Rules of the typing signal that need no socket or database."""

import uuid

from src.realtime.names import org_topic, room_topic
from src.realtime.typing_signal import (
    TYPING_GAP,
    SocketState,
    due,
    typing_event,
    typing_room,
)


def test_only_room_topics_take_the_signal() -> None:
    room_id = uuid.uuid7()
    assert typing_room(room_topic(room_id)) == room_id
    assert typing_room(org_topic(room_id)) is None
    assert typing_room("room:not-a-uuid") is None
    assert typing_room(None) is None


def test_one_signal_per_gap_for_each_room() -> None:
    state = SocketState(uuid.uuid7())
    first, second = room_topic(uuid.uuid7()), room_topic(uuid.uuid7())
    assert due(state, first, 100.0) is True
    assert due(state, first, 100.0 + TYPING_GAP / 2) is False
    assert due(state, second, 100.5) is True
    assert due(state, first, 100.0 + TYPING_GAP) is True


def test_event_carries_room_person_and_name() -> None:
    room_id, user_id = uuid.uuid7(), uuid.uuid7()
    assert typing_event(room_id, user_id, "Lan") == {
        "type": "typing",
        "room_id": str(room_id),
        "user_id": str(user_id),
        "name": "Lan",
    }
