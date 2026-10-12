"""Unit tests for workspace realtime: posts/chat channels + typing."""

from __future__ import annotations

import pytest
from fastapi import WebSocketDisconnect

from core.realtime import (
    Channel,
    TypingFrame,
    parse_channel,
    parse_client_frame,
)
from tests.unit.realtime_fakes import (
    FakeChatRooms,
    FakeMembership,
    clear_overrides,
    make_service,
    uid,
    ws_app,
)


def test_parse_workspace_channels() -> None:
    subject = uid()
    assert parse_channel(f"posts:{subject}") == Channel("posts", subject)
    assert parse_channel(f"chat:{subject}") == Channel("chat", subject)


def test_authorize_workspace_channels_member_only() -> None:
    user_id, other, org = uid(), uid(), uid()
    service = make_service(members=FakeMembership({(org, user_id)}))
    assert service.authorize(Channel("posts", org), user_id)
    assert service.authorize(Channel("chat", org), user_id)
    assert not service.authorize(Channel("posts", org), other)
    assert not service.authorize(Channel("chat", org), other)
    assert not service.authorize(Channel("chat", org), None)


def test_chat_channel_prefers_room_acl_port() -> None:
    """A wired ChatRoomAccess overrides the membership fallback."""
    user_id, room = uid(), uid()
    service = make_service(
        chat_rooms=FakeChatRooms({(room, user_id)})
    )
    assert service.authorize(Channel("chat", room), user_id)
    # Membership alone no longer opens a chat channel.
    assert not service.authorize(Channel("chat", uid()), user_id)


def test_parse_typing_frame() -> None:
    frame = parse_client_frame(
        '{"type":"typing.v1","data":{"channel":"chat:x"}}'
    )
    assert isinstance(frame, TypingFrame)
    assert frame.channel_name == "chat:x"


def test_typing_relays_to_chat_channel_members() -> None:
    """Two members on chat:{org}: one's typing.v1 reaches the other."""
    alice, bob, org = uid(), uid(), uid()
    client, _, service = ws_app(
        members=FakeMembership({(org, alice), (org, bob)})
    )
    try:
        token_a = service.issue_ticket(alice).token
        token_b = service.issue_ticket(bob).token
        with client.websocket_connect(f"/ws?ticket={token_a}") as sock_a:
            sock_a.receive_json()  # ready.v1
            sock_a.send_json(
                {"type": "subscribe.v1",
                 "data": {"channel": f"chat:{org}"}}
            )
            assert sock_a.receive_json()["type"] == "subscribed.v1"
            with client.websocket_connect(f"/ws?ticket={token_b}") as sock_b:
                sock_b.receive_json()  # ready.v1
                sock_b.send_json(
                    {"type": "subscribe.v1",
                     "data": {"channel": f"chat:{org}"}}
                )
                assert sock_b.receive_json()["type"] == "subscribed.v1"
                sock_a.send_json(
                    {"type": "typing.v1",
                     "data": {"channel": f"chat:{org}"}}
                )
                event = sock_b.receive_json()
                assert event["type"] == "event.v1"
                assert event["data"]["channel"] == f"chat:{org}"
                assert event["data"]["payload"] == {
                    "action": "typing",
                    "user_id": str(alice),
                }
    finally:
        clear_overrides()


def test_typing_denied_for_non_member_keeps_socket() -> None:
    """Denied typing sends a quiet error, never closes the socket."""
    alice, org = uid(), uid()
    client, _, service = ws_app(members=FakeMembership())
    try:
        token = service.issue_ticket(alice).token
        with client.websocket_connect(f"/ws?ticket={token}") as sock:
            sock.receive_json()  # ready.v1
            sock.send_json(
                {"type": "typing.v1",
                 "data": {"channel": f"chat:{org}"}}
            )
            err = sock.receive_json()
            assert err["type"] == "error.v1"
            assert err["data"]["code"] == "FORBIDDEN"
            # Still connected: a ping answers normally afterwards.
            sock.send_json({"type": "ping.v1", "data": {}})
            assert sock.receive_json()["type"] == "pong.v1"
    finally:
        clear_overrides()


def test_typing_on_non_chat_channel_is_ignored() -> None:
    """typing.v1 only targets chat:*; other channels are dropped."""
    alice, org = uid(), uid()
    client, _, service = ws_app(
        members=FakeMembership({(org, alice)})
    )
    try:
        token = service.issue_ticket(alice).token
        with client.websocket_connect(f"/ws?ticket={token}") as sock:
            sock.receive_json()  # ready.v1
            sock.send_json(
                {"type": "typing.v1",
                 "data": {"channel": f"members:{org}"}}
            )
            # No error frame: the next received frame answers the ping.
            sock.send_json({"type": "ping.v1", "data": {}})
            assert sock.receive_json()["type"] == "pong.v1"
    finally:
        clear_overrides()


def test_subscribe_posts_channel_acl() -> None:
    """Member subscribes posts:{org}; an outsider is refused with 4403."""
    alice, outsider, org = uid(), uid(), uid()
    client, _, service = ws_app(
        members=FakeMembership({(org, alice)})
    )
    try:
        token = service.issue_ticket(alice).token
        with client.websocket_connect(f"/ws?ticket={token}") as sock:
            sock.receive_json()
            sock.send_json(
                {"type": "subscribe.v1",
                 "data": {"channel": f"posts:{org}"}}
            )
            assert sock.receive_json()["type"] == "subscribed.v1"
        bad = service.issue_ticket(outsider).token
        with client.websocket_connect(f"/ws?ticket={bad}") as sock:
            sock.receive_json()
            sock.send_json(
                {"type": "subscribe.v1",
                 "data": {"channel": f"chat:{org}"}}
            )
            assert sock.receive_json()["data"]["code"] == "FORBIDDEN"
            with pytest.raises(WebSocketDisconnect) as closed:
                sock.receive_json()
            assert closed.value.code == 4403
    finally:
        clear_overrides()
