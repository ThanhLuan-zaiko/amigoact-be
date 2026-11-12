import json
import uuid
from typing import Any, cast

import anyio
import pytest
from sqlalchemy.orm import Session
from starlette.websockets import WebSocket

from src.realtime import bus, listener
from src.realtime.hub import Hub, revoked_frame
from src.realtime.names import (
    managers_topic,
    org_topic,
    parse_topic,
    room_topic,
    user_topic,
)


class FakeSocket:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail = fail

    async def send_json(self, body: dict[str, Any]) -> None:
        if self.fail:
            raise RuntimeError("closed")
        self.sent.append(body)


def ws(fake: FakeSocket) -> WebSocket:
    return cast(WebSocket, fake)


def test_topic_names_round_trip() -> None:
    target = uuid.uuid7()
    for kind, name in (
        ("user", user_topic(target)),
        ("org", org_topic(target)),
        ("org-managers", managers_topic(target)),
        ("room", room_topic(target)),
    ):
        assert parse_topic(name) == (kind, target)


@pytest.mark.parametrize(
    "bad", ["", "room", "room:", "room:abc", "post:" + str(uuid.uuid7()), 5, None]
)
def test_unknown_topics_are_refused(bad: object) -> None:
    assert parse_topic(bad) is None


def test_register_joins_the_own_topic_only() -> None:
    hub = Hub()
    me, other = uuid.uuid7(), uuid.uuid7()
    socket = FakeSocket()
    hub.register(ws(socket), me)

    assert hub.is_online(me)
    assert not hub.is_online(other)
    hub.unregister(ws(socket))
    assert not hub.is_online(me)


def test_broadcast_adds_the_topic_and_reaches_only_listeners() -> None:
    hub = Hub()
    topic, other = room_topic(uuid.uuid7()), room_topic(uuid.uuid7())
    listening, bystander = FakeSocket(), FakeSocket()
    hub.subscribe(topic, ws(listening))
    hub.subscribe(other, ws(bystander))

    anyio.run(hub.broadcast, topic, {"type": "x"})

    assert listening.sent == [{"type": "x", "topic": topic}]
    assert bystander.sent == []


def test_broadcast_drops_a_socket_that_fails() -> None:
    hub = Hub()
    topic = org_topic(uuid.uuid7())
    broken, healthy = FakeSocket(fail=True), FakeSocket()
    hub.register(ws(broken), uuid.uuid7())
    hub.subscribe(topic, ws(broken))
    hub.subscribe(topic, ws(healthy))

    anyio.run(hub.broadcast, topic, {"type": "x"})
    anyio.run(hub.broadcast, topic, {"type": "y"})

    assert [frame["type"] for frame in healthy.sent] == ["x", "y"]


def test_revoke_cuts_only_the_named_person() -> None:
    hub = Hub()
    room_id = uuid.uuid7()
    topic = room_topic(room_id)
    gone_user, staying_user = uuid.uuid7(), uuid.uuid7()
    gone, staying = FakeSocket(), FakeSocket()
    hub.register(ws(gone), gone_user)
    hub.register(ws(staying), staying_user)
    hub.subscribe(topic, ws(gone))
    hub.subscribe(topic, ws(staying))

    anyio.run(hub.revoke, [topic, org_topic(uuid.uuid7())], gone_user)

    assert gone.sent == [{"op": "revoked", "topic": topic, "room_id": str(room_id)}]
    assert staying.sent == []
    assert hub.has_listeners(topic)


def test_revoked_frame_has_room_id_for_rooms_only() -> None:
    org = org_topic(uuid.uuid7())
    assert revoked_frame(org) == {"op": "revoked", "topic": org}


def test_small_events_keep_their_body() -> None:
    message = bus.emit_message("org:x", {"type": "members.changed"})
    assert json.loads(bus.encode(message))["e"] == {"type": "members.changed"}


def test_oversized_events_become_a_resync_signal() -> None:
    message = bus.emit_message("room:x", {"type": "message.created", "b": "x" * 9000})
    payload = bus.encode(message)

    assert len(payload.encode()) < bus.PAYLOAD_LIMIT
    assert json.loads(payload)["e"] == {"type": "resync", "was": "message.created"}


def test_events_wait_for_the_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Any, Any]] = []
    monkeypatch.setattr(bus, "deliver_event", lambda t, b: calls.append(("e", t, b)))
    monkeypatch.setattr(bus, "deliver_revoke", lambda u, t: calls.append(("r", u, t)))
    monkeypatch.setattr(bus.runtime, "engine", None)
    db = Session()
    user_id = uuid.uuid7()

    bus.emit(db, "org:a", {"type": "x"})
    bus.revoke(db, user_id, ["org:a"])
    assert calls == []
    bus._deliver_queue(db)
    assert calls == [("e", "org:a", {"type": "x"}), ("r", user_id, ["org:a"])]

    bus.emit(db, "org:a", {"type": "y"})
    bus._drop_queue(db)
    bus._deliver_queue(db)
    assert len(calls) == 2


def test_delivery_outside_the_server_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = Hub()
    socket = FakeSocket()
    hub.subscribe("org:a", ws(socket))
    monkeypatch.setattr(bus, "hub", hub)
    monkeypatch.setattr(bus.runtime, "token", None)

    # No event loop token and no worker thread: nothing to deliver to, no error.
    bus.deliver_event("org:a", {"type": "x"})

    assert socket.sent == []


def test_listener_skips_own_and_malformed_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[Any] = []
    monkeypatch.setattr(bus, "deliver_event", lambda t, b: seen.append((t, b)))
    monkeypatch.setattr(bus, "deliver_revoke", lambda u, t: seen.append((u, t)))
    user_id = uuid.uuid7()
    foreign = {"o": "another-worker"}

    listener.handle(json.dumps(bus.emit_message("org:a", {"type": "x"})))
    listener.handle("not json")
    listener.handle('{"k":"wake"}')
    listener.handle(json.dumps({**foreign, "k": "revoke", "u": "bad", "ts": []}))
    assert seen == []

    listener.handle(
        json.dumps({**foreign, "k": "emit", "t": "org:a", "e": {"type": "x"}})
    )
    listener.handle(
        json.dumps({**foreign, "k": "revoke", "u": str(user_id), "ts": ["org:a"]})
    )
    assert seen == [("org:a", {"type": "x"}), (user_id, ["org:a"])]
