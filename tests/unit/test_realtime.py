"""Unit tests for realtime: envelopes, channels, service, registry."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fastapi import WebSocketDisconnect

from core.realtime import (
    BadFrameError,
    Channel,
    ConnectionManager,
    PingFrame,
    PongFrame,
    SubscribeFrame,
    UnknownFrame,
    UnsubscribeFrame,
    encode_envelope,
    parse_channel,
    parse_client_frame,
)
from core.security import utcnow
from tests.unit.realtime_fakes import (
    FakeMembership,
    FakeSocket,
    MemTickets,
    clear_overrides,
    make_service,
    uid,
    ws,
    ws_app,
)


def test_parse_valid_frames() -> None:
    assert isinstance(parse_client_frame('{"type":"pong.v1"}'), PongFrame)
    assert isinstance(parse_client_frame('{"type":"ping.v1","data":{}}'), PingFrame)
    sub = parse_client_frame(
        '{"type":"subscribe.v1","data":{"channel":"notifications:x"}}'
    )
    assert isinstance(sub, SubscribeFrame)
    assert sub.channel_name == "notifications:x"
    unsub = parse_client_frame(
        '{"type":"unsubscribe.v1","data":{"channel":"a:1"}}'
    )
    assert isinstance(unsub, UnsubscribeFrame)


def test_unknown_frame_never_crashes() -> None:
    frame = parse_client_frame('{"type":"future.v9","data":{"x":1}}')
    assert isinstance(frame, UnknownFrame)
    assert frame.frame_type == "future.v9"


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        "[1,2]",
        '{"data":{}}',
        '{"type":5}',
        '{"type":"pong.v1","data":[1]}',
    ],
)
def test_bad_frames_raise(raw: str) -> None:
    with pytest.raises(BadFrameError):
        parse_client_frame(raw)


def test_encode_envelope_shape() -> None:
    raw = encode_envelope("ping.v1", {"ts": "t"})
    assert json.loads(raw) == {"type": "ping.v1", "data": {"ts": "t"}}
    assert json.loads(encode_envelope("pong.v1")) == {
        "type": "pong.v1",
        "data": {},
    }


def test_parse_channel() -> None:
    subject = uid()
    channel = parse_channel(f"notifications:{subject}")
    assert channel == Channel(kind="notifications", subject=subject)
    assert parse_channel(f"attendance:{subject}").kind == "attendance"  # type: ignore[union-attr]
    assert parse_channel(f"activities:{subject}").kind == "activities"  # type: ignore[union-attr]
    assert parse_channel(f"members:{subject}").kind == "members"  # type: ignore[union-attr]
    assert parse_channel("weird") is None
    assert parse_channel("admins:x") is None
    assert parse_channel("notifications:not-a-uuid") is None


def test_ticket_single_use_and_expiry() -> None:
    store = MemTickets()
    service = make_service(store)
    user_id = uid()
    issued = service.issue_ticket(user_id)
    assert issued.expires_in == 60
    assert len(store.rows) == 1
    assert issued.token not in store.rows  # hash only, never plaintext

    assert service.consume_ticket(issued.token) == user_id
    assert service.consume_ticket(issued.token) is None  # single use

    spent = service.issue_ticket(user_id)
    row = next(iter(store.rows.values()))
    row.expires_at = utcnow() - timedelta(seconds=1)
    assert service.consume_ticket(spent.token) is None
    assert service.consume_ticket("garbage") is None


def test_authorize_channels() -> None:
    user_id, other, org = uid(), uid(), uid()
    service = make_service(members=FakeMembership({(org, user_id)}))
    assert service.authorize(Channel("notifications", user_id), user_id)
    assert not service.authorize(Channel("notifications", other), user_id)
    assert service.authorize(Channel("activities", org), user_id)
    assert not service.authorize(Channel("activities", org), other)
    assert service.authorize(Channel("members", org), user_id)
    assert not service.authorize(Channel("members", org), other)
    assert not service.authorize(Channel("attendance", org), user_id)


async def test_manager_subscribe_publish_unregister() -> None:
    manager = ConnectionManager()
    a, b = FakeSocket(), FakeSocket()
    user_id = uid()
    manager.register(ws(a), user_id)
    manager.register(ws(b), user_id)
    channel = f"notifications:{user_id}"
    assert manager.subscribe(ws(a), channel)
    assert not manager.subscribe(ws(a), channel)
    manager.subscribe(ws(b), channel)

    assert await manager.publish(channel, {"n": 1}) == 2
    assert a.sent[0]["type"] == "event.v1"
    assert a.sent[0]["data"]["channel"] == channel
    assert a.sent[0]["data"]["payload"] == {"n": 1}

    assert manager.unsubscribe(ws(a), channel)
    assert not manager.unsubscribe(ws(a), channel)
    assert await manager.publish(channel) == 1

    manager.unregister(ws(b))
    assert await manager.publish(channel) == 0


def test_handshake_ready_and_frames() -> None:
    client, _, service = ws_app()
    try:
        user_id = uid()
        token = service.issue_ticket(user_id).token
        with client.websocket_connect(f"/ws?ticket={token}") as sock:
            ready = sock.receive_json()
            assert ready["type"] == "ready.v1"
            assert ready["data"]["user_id"] == str(user_id)
            assert ready["data"]["channels"] == [f"notifications:{user_id}"]
            sock.send_json({"type": "future.v9", "data": {}})  # ignored
            sock.send_json({"type": "ping.v1", "data": {}})
            pong = sock.receive_json()
            assert pong == {"type": "pong.v1", "data": {}}
            sock.send_text("garbage")
            err = sock.receive_json()
            assert err["type"] == "error.v1"
            assert err["data"]["code"] == "BAD_FRAME"
            with pytest.raises(WebSocketDisconnect) as closed:
                sock.receive_json()
            assert closed.value.code == 4400
    finally:
        clear_overrides()


def test_handshake_denies_bad_ticket() -> None:
    client, _, _ = ws_app()
    try:
        with client.websocket_connect("/ws?ticket=wrong") as sock:
            with pytest.raises(WebSocketDisconnect) as closed:
                sock.receive_json()
            assert closed.value.code == 4401
    finally:
        clear_overrides()


def test_subscribe_acl() -> None:
    user_id, other, org = uid(), uid(), uid()
    client, _, service = ws_app(members=FakeMembership({(org, user_id)}))
    try:
        token = service.issue_ticket(user_id).token
        with client.websocket_connect(f"/ws?ticket={token}") as sock:
            sock.receive_json()  # ready.v1
            sock.send_json(
                {
                    "type": "subscribe.v1",
                    "data": {"channel": f"activities:{org}"},
                }
            )
            ack = sock.receive_json()
            assert ack["type"] == "subscribed.v1"
            assert ack["data"]["channel"] == f"activities:{org}"
            sock.send_json(
                {
                    "type": "subscribe.v1",
                    "data": {"channel": f"notifications:{other}"},
                }
            )
            err = sock.receive_json()
            assert err["data"]["code"] == "FORBIDDEN"
            with pytest.raises(WebSocketDisconnect) as closed:
                sock.receive_json()
            assert closed.value.code == 4403
    finally:
        clear_overrides()


def test_heartbeat_closes_silent_client() -> None:
    client, _, service = ws_app(heartbeat=1, pong_timeout=1)
    try:
        user_id = uid()
        token = service.issue_ticket(user_id).token
        with client.websocket_connect(f"/ws?ticket={token}") as sock:
            assert sock.receive_json()["type"] == "ready.v1"
            saw_ping = False
            with pytest.raises(WebSocketDisconnect) as closed:
                for _ in range(6):
                    frame = sock.receive_json()
                    saw_ping = saw_ping or frame["type"] == "ping.v1"
            assert saw_ping
            assert closed.value.code == 4408
    finally:
        clear_overrides()
