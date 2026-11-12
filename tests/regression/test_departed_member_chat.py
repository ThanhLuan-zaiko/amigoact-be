"""A socket checks access when it subscribes, so leaving must cut rooms it already holds."""

from tests.activity_helpers import Bearer, user
from tests.chat_helpers import sent, ticket
from tests.conftest import ApiContext
from tests.notification_helpers import heard_nothing, next_frame
from tests.post_helpers import join, open_org


def _room(api: ApiContext, slug: str, headers: dict[str, str]) -> str:
    value: str = api.client.get(f"/organizations/{slug}", headers=headers).json()["id"]
    return value


def test_member_who_left_stops_hearing_the_room(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "owner")
    member, _ = user(api, bearer, "member")
    slug = open_org(api, owner)
    join(api, slug, member)
    room = _room(api, slug, owner)

    with api.client.websocket_connect(f"/ws/chat?ticket={ticket(api, member)}") as ws:
        ws.send_json({"op": "subscribe", "room_id": room})
        assert ws.receive_json()["op"] == "subscribed"
        api.client.delete(f"/organizations/{slug}/membership", headers=member)
        assert next_frame(ws) == {"op": "revoked", "room_id": room}

        sent(api, owner, room, "Not for you")
        assert heard_nothing(ws)


def test_removed_member_stops_hearing_the_room(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    member, member_id = user(api, bearer, "member")
    slug = open_org(api, owner)
    join(api, slug, member)
    room = _room(api, slug, owner)

    with api.client.websocket_connect(f"/ws/chat?ticket={ticket(api, member)}") as ws:
        ws.send_json({"op": "subscribe", "room_id": room})
        assert ws.receive_json()["op"] == "subscribed"
        api.client.delete(f"/organizations/{slug}/members/{member_id}", headers=owner)
        ws.send_json({"op": "ping"})
        frames = []
        while (frame := ws.receive_json()) != {"op": "pong"}:
            frames.append(frame)

        sent(api, owner, room, "Not for you")
        assert heard_nothing(ws)

    assert {"op": "revoked", "topic": f"room:{room}", "room_id": room} in frames
    pushed = [f for f in frames if f.get("type") == "notification.created"]
    assert [f["notification"]["type"] for f in pushed] == ["membership_removed"]


def test_failed_leave_cuts_nothing(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "owner")
    slug = open_org(api, owner)
    room = _room(api, slug, owner)

    with api.client.websocket_connect(f"/ws/chat?ticket={ticket(api, owner)}") as ws:
        ws.send_json({"op": "subscribe", "room_id": room})
        assert ws.receive_json()["op"] == "subscribed"
        refused = api.client.delete(f"/organizations/{slug}/membership", headers=owner)
        assert heard_nothing(ws)

    assert refused.json()["detail"] == "owner_cannot_leave"
