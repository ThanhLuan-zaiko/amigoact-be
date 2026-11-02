import uuid
from typing import Any, cast

import anyio
import pytest
from pydantic import ValidationError
from starlette.websockets import WebSocket

from src.chat.hub import ChatHub
from src.chat.rules import EMOJI_MAX, MESSAGE_LIMIT, REPLY_PREVIEW
from src.chat.schemas import ChannelCreate, DmOpen, MessageSend, ReactionAdd


class FakeSocket:
    """Stands in for a WebSocket. It records what would have been sent."""

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail = fail

    async def send_json(self, body: dict[str, Any]) -> None:
        if self.fail:
            raise RuntimeError("closed")
        self.sent.append(body)


def _socket(fake: FakeSocket) -> WebSocket:
    return cast(WebSocket, fake)


def test_message_body_is_trimmed_and_bounded() -> None:
    assert MessageSend(body="  Chao  ").body == "Chao"
    with pytest.raises(ValidationError):
        MessageSend(body="   ")
    with pytest.raises(ValidationError):
        MessageSend(body="x" * (MESSAGE_LIMIT + 1))


def test_reply_must_name_a_message_id_in_uuid7() -> None:
    with pytest.raises(ValidationError):
        MessageSend(body="a", reply_to_id=uuid.uuid4())


def test_channel_name_and_visibility_are_checked() -> None:
    with pytest.raises(ValidationError):
        ChannelCreate(name="a\nb")
    with pytest.raises(ValidationError):
        ChannelCreate(name="x" * 41)
    with pytest.raises(ValidationError):
        ChannelCreate(name="Chung", visibility="secret")
    assert ChannelCreate(name="  Chung  ").visibility == "open"


def test_reaction_emoji_has_a_length_limit() -> None:
    assert ReactionAdd(emoji="+1").emoji == "+1"
    with pytest.raises(ValidationError):
        ReactionAdd(emoji="")
    with pytest.raises(ValidationError):
        ReactionAdd(emoji="x" * (EMOJI_MAX + 1))


def test_direct_message_needs_a_uuid7_peer() -> None:
    with pytest.raises(ValidationError):
        DmOpen(user_id=uuid.uuid4())


def test_reply_preview_keeps_a_short_quote() -> None:
    assert REPLY_PREVIEW == 200


def test_hub_tracks_listeners_per_room() -> None:
    hub = ChatHub()
    room = uuid.uuid7()
    first = _socket(FakeSocket())
    second = _socket(FakeSocket())

    hub.subscribe(room, first)
    hub.subscribe(room, second)
    assert hub.has_listeners(room)
    hub.unsubscribe(room, first)
    hub.unsubscribe(room, second)
    assert not hub.has_listeners(room)


def test_unregistering_a_socket_removes_it_from_every_room() -> None:
    hub = ChatHub()
    socket = _socket(FakeSocket())
    rooms = [uuid.uuid7(), uuid.uuid7()]
    hub.register(socket, uuid.uuid7())
    for room in rooms:
        hub.subscribe(room, socket)

    hub.unregister(socket)

    assert not any(hub.has_listeners(room) for room in rooms)


def test_broadcast_reaches_only_the_room_listeners() -> None:
    hub = ChatHub()
    room, other = uuid.uuid7(), uuid.uuid7()
    listener = FakeSocket()
    bystander = FakeSocket()
    hub.subscribe(room, _socket(listener))
    hub.subscribe(other, _socket(bystander))

    anyio.run(hub.broadcast, room, {"type": "message.created"})

    assert listener.sent == [{"type": "message.created"}]
    assert bystander.sent == []


def test_broadcast_drops_a_socket_that_fails() -> None:
    hub = ChatHub()
    room = uuid.uuid7()
    broken = FakeSocket(fail=True)
    healthy = FakeSocket()
    hub.register(_socket(broken), uuid.uuid7())
    hub.subscribe(room, _socket(broken))
    hub.subscribe(room, _socket(healthy))

    anyio.run(hub.broadcast, room, {"type": "message.created"})

    assert healthy.sent == [{"type": "message.created"}]
    assert hub.has_listeners(room)
    anyio.run(hub.broadcast, room, {"type": "again"})
    assert healthy.sent[-1] == {"type": "again"}


def test_revoke_only_affects_the_named_person() -> None:
    hub = ChatHub()
    room = uuid.uuid7()
    removed_user, staying_user = uuid.uuid7(), uuid.uuid7()
    removed = FakeSocket()
    staying = FakeSocket()
    hub.register(_socket(removed), removed_user)
    hub.register(_socket(staying), staying_user)
    hub.subscribe(room, _socket(removed))
    hub.subscribe(room, _socket(staying))

    anyio.run(hub.revoke, room, removed_user)

    assert removed.sent == [{"op": "revoked", "room_id": str(room)}]
    assert staying.sent == []
    assert hub.has_listeners(room)
