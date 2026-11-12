import uuid

import pytest
from sqlalchemy import update
from starlette.websockets import WebSocketDisconnect

from src.app import app
from src.models.chat import WsTicket
from tests.activity_helpers import Bearer, user
from tests.chat_helpers import channel, ticket
from tests.conftest import ApiContext
from tests.post_helpers import join, open_org


def test_ticket_needs_a_login(api: ApiContext) -> None:
    assert api.client.post("/chat/tickets").status_code == 401


def test_ticket_works_once(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "once")
    spent = ticket(api, owner)

    with api.client.websocket_connect(f"/ws/chat?ticket={spent}") as socket:
        socket.send_json({"op": "ping"})
        assert socket.receive_json() == {"op": "pong"}
    with (
        pytest.raises(WebSocketDisconnect) as reused,
        api.client.websocket_connect(f"/ws/chat?ticket={spent}"),
    ):
        pass

    assert reused.value.code == 4401


def test_forged_and_expired_tickets_are_refused(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, owner_id = user(api, bearer, "expired")
    old = ticket(api, owner)
    with app.state.engine.begin() as connection:
        connection.execute(
            update(WsTicket)
            .where(WsTicket.user_id == uuid.UUID(owner_id))
            .values(expires_at="2000-01-01T00:00:00+00:00")
        )

    with (
        pytest.raises(WebSocketDisconnect),
        api.client.websocket_connect(f"/ws/chat?ticket={old}"),
    ):
        pass
    with (
        pytest.raises(WebSocketDisconnect),
        api.client.websocket_connect("/ws/chat?ticket=forged-ticket"),
    ):
        pass


def test_socket_rejects_bad_frames_and_foreign_rooms(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "frames")
    peer, peer_id = user(api, bearer, "frames_peer")
    intruder, _ = user(api, bearer, "frames_intruder")
    slug = open_org(api, owner)
    join(api, slug, peer)
    join(api, slug, intruder)
    dm_room = api.client.post(
        f"/organizations/{slug}/chat/dms", headers=owner, json={"user_id": peer_id}
    ).json()["room_id"]

    with api.client.websocket_connect(
        f"/ws/chat?ticket={ticket(api, intruder)}"
    ) as socket:
        socket.send_json("text instead of object")
        assert socket.receive_json() == {"op": "error", "code": "bad_frame"}
        socket.send_json({"op": "dance"})
        assert socket.receive_json() == {"op": "error", "code": "unknown_op"}
        socket.send_json({"op": "subscribe", "room_id": "not-a-uuid"})
        assert socket.receive_json() == {"op": "error", "code": "room_id_invalid"}
        socket.send_json({"op": "subscribe", "room_id": dm_room})
        assert socket.receive_json() == {"op": "error", "code": "room_not_found"}


def test_removed_channel_member_is_cut_off_live(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "cutter")
    member, member_id = user(api, bearer, "cut_member")
    slug = open_org(api, owner)
    join(api, slug, member)
    room = channel(
        api, owner, slug, "Co han", visibility="restricted", member_ids=[member_id]
    )

    with api.client.websocket_connect(
        f"/ws/chat?ticket={ticket(api, member)}"
    ) as socket:
        socket.send_json({"op": "subscribe", "room_id": room["id"]})
        assert socket.receive_json()["op"] == "subscribed"
        removed = api.client.delete(
            f"/chat/channels/{room['id']}/members/{member_id}", headers=owner
        )
        assert removed.status_code == 204
        assert socket.receive_json() == {
            "op": "revoked",
            "topic": f"room:{room['id']}",
            "room_id": room["id"],
        }
