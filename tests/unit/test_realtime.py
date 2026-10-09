"""Unit tests for realtime: envelopes, channels, service, registry."""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
import uuid_utils
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient

from core.config import Settings
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
from realtime.interfaces import OrgMembership, WsTicketStore
from realtime.service import RealtimeService


def _uid() -> UUID:
    return UUID(str(uuid_utils.uuid7()))


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
    uid = _uid()
    channel = parse_channel(f"notifications:{uid}")
    assert channel == Channel(kind="notifications", subject=uid)
    assert parse_channel(f"attendance:{uid}").kind == "attendance"  # type: ignore[union-attr]
    assert parse_channel(f"activities:{uid}").kind == "activities"  # type: ignore[union-attr]
    assert parse_channel("weird") is None
    assert parse_channel("admins:x") is None
    assert parse_channel("notifications:not-a-uuid") is None


class _MemTickets(WsTicketStore):
    """In-memory single-use ticket rows."""

    def __init__(self) -> None:
        self.rows: dict[str, SimpleNamespace] = {}

    def create(self, ticket_hash, user_id, expires_at, now) -> None:  # noqa: ANN001, ANN202
        self.rows[ticket_hash] = SimpleNamespace(
            ticket_hash=ticket_hash,
            user_id=user_id,
            expires_at=expires_at,
            created_at=now,
        )

    def consume(self, ticket_hash):  # noqa: ANN001, ANN202
        return self.rows.pop(ticket_hash, None)


class _Membership(OrgMembership):
    def __init__(self, pairs: set[tuple[UUID, UUID]] | None = None) -> None:
        self._pairs = pairs or set()

    def is_member(self, org_id: UUID, user_id: UUID) -> bool:
        return (org_id, user_id) in self._pairs


def _service(store: _MemTickets | None = None, members=None) -> RealtimeService:
    return RealtimeService(
        tickets=store or _MemTickets(),
        membership=members or _Membership(),
        attendance=None,
        ticket_ttl_seconds=60,
    )


def test_ticket_single_use_and_expiry() -> None:
    store = _MemTickets()
    service = _service(store)
    uid = _uid()
    issued = service.issue_ticket(uid)
    assert issued.expires_in == 60
    assert len(store.rows) == 1
    assert issued.token not in store.rows  # hash only, never plaintext

    assert service.consume_ticket(issued.token) == uid
    assert service.consume_ticket(issued.token) is None  # single use

    spent = service.issue_ticket(uid)
    row = next(iter(store.rows.values()))
    row.expires_at = utcnow() - timedelta(seconds=1)
    assert service.consume_ticket(spent.token) is None
    assert service.consume_ticket("garbage") is None


def test_authorize_channels() -> None:
    uid, other, org = _uid(), _uid(), _uid()
    service = _service(members=_Membership({(org, uid)}))
    assert service.authorize(Channel("notifications", uid), uid)
    assert not service.authorize(Channel("notifications", other), uid)
    assert service.authorize(Channel("activities", org), uid)
    assert not service.authorize(Channel("activities", org), other)
    assert not service.authorize(Channel("attendance", org), uid)


class _Socket:
    """Duck-typed WebSocket recording every frame and close code."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.closed: int | None = None

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = code


def _ws(sock: _Socket) -> WebSocket:
    return cast(WebSocket, sock)


async def test_manager_subscribe_publish_unregister() -> None:
    manager = ConnectionManager()
    a, b = _Socket(), _Socket()
    uid = _uid()
    manager.register(_ws(a), uid)
    manager.register(_ws(b), uid)
    channel = f"notifications:{uid}"
    assert manager.subscribe(_ws(a), channel)
    assert not manager.subscribe(_ws(a), channel)
    manager.subscribe(_ws(b), channel)

    assert await manager.publish(channel, {"n": 1}) == 2
    assert a.sent[0]["type"] == "event.v1"
    assert a.sent[0]["data"]["channel"] == channel
    assert a.sent[0]["data"]["payload"] == {"n": 1}

    assert manager.unsubscribe(_ws(a), channel)
    assert not manager.unsubscribe(_ws(a), channel)
    assert await manager.publish(channel) == 1

    manager.unregister(_ws(b))
    assert await manager.publish(channel) == 0


def _ws_app(
    members: _Membership | None = None,
    heartbeat: int = 120,
    pong_timeout: int = 120,
) -> tuple[TestClient, _MemTickets, RealtimeService]:
    """App with realtime deps swapped for in-memory fakes (no ScyllaDB)."""
    import main
    from core.config import get_settings
    from core.dependencies import get_realtime_service
    from core.realtime import ConnectionManager

    store = _MemTickets()
    service = RealtimeService(store, members or _Membership(), None, 60)
    settings = Settings(
        jwt_secret="unit-test-secret-32-bytes-padded!",
        env="dev",
        ws_heartbeat_seconds=heartbeat,
        ws_pong_timeout_seconds=pong_timeout,
    )
    if getattr(main.app.state, "ws_manager", None) is None:
        main.app.state.ws_manager = ConnectionManager()
    main.app.dependency_overrides.update(
        {
            get_realtime_service: lambda: service,
            get_settings: lambda: settings,
        }
    )
    return TestClient(main.app), store, service


def _clear_overrides() -> None:
    import main

    main.app.dependency_overrides.clear()


def test_handshake_ready_and_frames() -> None:
    client, _, service = _ws_app()
    try:
        uid = _uid()
        token = service.issue_ticket(uid).token
        with client.websocket_connect(f"/ws?ticket={token}") as ws:
            ready = ws.receive_json()
            assert ready["type"] == "ready.v1"
            assert ready["data"]["user_id"] == str(uid)
            assert ready["data"]["channels"] == [f"notifications:{uid}"]
            ws.send_json({"type": "future.v9", "data": {}})  # ignored
            ws.send_json({"type": "ping.v1", "data": {}})
            pong = ws.receive_json()
            assert pong == {"type": "pong.v1", "data": {}}
            ws.send_text("garbage")
            err = ws.receive_json()
            assert err["type"] == "error.v1"
            assert err["data"]["code"] == "BAD_FRAME"
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == 4400
    finally:
        _clear_overrides()


def test_handshake_denies_bad_ticket() -> None:
    client, _, _ = _ws_app()
    try:
        with client.websocket_connect("/ws?ticket=wrong") as ws:
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == 4401
    finally:
        _clear_overrides()


def test_subscribe_acl() -> None:
    uid, other, org = _uid(), _uid(), _uid()
    client, _, service = _ws_app(members=_Membership({(org, uid)}))
    try:
        token = service.issue_ticket(uid).token
        with client.websocket_connect(f"/ws?ticket={token}") as ws:
            ws.receive_json()  # ready.v1
            ws.send_json(
                {
                    "type": "subscribe.v1",
                    "data": {"channel": f"activities:{org}"},
                }
            )
            ack = ws.receive_json()
            assert ack["type"] == "subscribed.v1"
            assert ack["data"]["channel"] == f"activities:{org}"
            ws.send_json(
                {
                    "type": "subscribe.v1",
                    "data": {"channel": f"notifications:{other}"},
                }
            )
            err = ws.receive_json()
            assert err["data"]["code"] == "FORBIDDEN"
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == 4403
    finally:
        _clear_overrides()


def test_heartbeat_closes_silent_client() -> None:
    client, _, service = _ws_app(heartbeat=1, pong_timeout=1)
    try:
        uid = _uid()
        token = service.issue_ticket(uid).token
        with client.websocket_connect(f"/ws?ticket={token}") as ws:
            assert ws.receive_json()["type"] == "ready.v1"
            saw_ping = False
            with pytest.raises(WebSocketDisconnect) as closed:
                for _ in range(6):
                    frame = ws.receive_json()
                    saw_ping = saw_ping or frame["type"] == "ping.v1"
            assert saw_ping
            assert closed.value.code == 4408
    finally:
        _clear_overrides()
