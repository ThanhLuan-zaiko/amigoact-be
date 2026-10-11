"""Unit tests for the attendance:{activity_id} live channel (16)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import WebSocketDisconnect

from core.realtime import Channel, ConnectionManager
from tests.unit.realtime_fakes import (
    FakeAttendance,
    FakeSocket,
    clear_overrides,
    make_service,
    uid,
    ws,
    ws_app,
)


def test_authorize_attendance_channel() -> None:
    """ACL delegates to the AttendanceAccess port; closed when unwired."""
    user, stranger, aid = uid(), uid(), uid()
    service = make_service(attendance=FakeAttendance({(aid, user)}))
    assert service.authorize(Channel("attendance", aid), user)
    assert not service.authorize(Channel("attendance", aid), stranger)
    assert not make_service().authorize(Channel("attendance", aid), user)


def test_subscribe_attendance_channel() -> None:
    """Allowed staff join; denied users get error.v1 FORBIDDEN + 4403."""
    user, stranger, aid = uid(), uid(), uid()
    client, _, service = ws_app(attendance=FakeAttendance({(aid, user)}))
    try:
        token = service.issue_ticket(user).token
        with client.websocket_connect(f"/ws?ticket={token}") as sock:
            sock.receive_json()  # ready.v1
            sock.send_json(
                {
                    "type": "subscribe.v1",
                    "data": {"channel": f"attendance:{aid}"},
                }
            )
            ack = sock.receive_json()
            assert ack["type"] == "subscribed.v1"
            assert ack["data"]["channel"] == f"attendance:{aid}"

        token = service.issue_ticket(stranger).token
        with client.websocket_connect(f"/ws?ticket={token}") as sock:
            sock.receive_json()  # ready.v1
            sock.send_json(
                {
                    "type": "subscribe.v1",
                    "data": {"channel": f"attendance:{aid}"},
                }
            )
            err = sock.receive_json()
            assert err["data"]["code"] == "FORBIDDEN"
            with pytest.raises(WebSocketDisconnect) as closed:
                sock.receive_json()
            assert closed.value.code == 4403
    finally:
        clear_overrides()


async def test_schedule_publish_from_sync_endpoint_thread() -> None:
    """Sync def endpoints run in the threadpool (no running loop); the
    send must still land via the loop bound at register()."""
    manager = ConnectionManager()
    sock = FakeSocket()
    manager.register(ws(sock), uid())
    channel = f"attendance:{uid()}"
    manager.subscribe(ws(sock), channel)

    sent = await asyncio.to_thread(
        manager.schedule_publish, channel, {"action": "checked_in"}
    )
    assert sent
    for _ in range(100):
        if sock.sent:
            break
        await asyncio.sleep(0.01)
    assert sock.sent[0]["type"] == "event.v1"
    assert sock.sent[0]["data"]["channel"] == channel
    assert sock.sent[0]["data"]["payload"] == {"action": "checked_in"}


def test_schedule_publish_without_any_loop() -> None:
    """No running loop and nothing bound: False, no delivery attempt."""
    assert ConnectionManager().schedule_publish("x:y", {}) is False
