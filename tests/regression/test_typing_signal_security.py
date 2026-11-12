"""The typing signal must not reach rooms the socket could not subscribe to."""

from tests.activity_helpers import Bearer, user
from tests.chat_helpers import sent, ticket
from tests.conftest import ApiContext
from tests.post_helpers import open_org


def test_typing_needs_a_subscribed_room_topic(api: ApiContext, bearer: Bearer) -> None:
    owner, _ = user(api, bearer, "host")
    stranger, _ = user(api, bearer, "outsider")
    slug = open_org(api, owner)
    org_id = api.client.get(f"/organizations/{slug}", headers=owner).json()["id"]
    topic = f"room:{org_id}"

    with api.client.websocket_connect(f"/ws?ticket={ticket(api, stranger)}") as socket:
        socket.send_json({"op": "typing", "topic": topic})
        assert socket.receive_json() == {"op": "error", "code": "topic_not_found"}
        socket.send_json({"op": "typing", "topic": f"org:{org_id}"})
        assert socket.receive_json() == {"op": "error", "code": "topic_invalid"}
        socket.send_json({"op": "subscribe", "topic": topic})
        assert socket.receive_json() == {"op": "error", "code": "topic_not_found"}
        socket.send_json({"op": "typing", "topic": topic})
        assert socket.receive_json() == {"op": "error", "code": "topic_not_found"}


def test_repeated_signals_inside_the_gap_are_dropped(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, _ = user(api, bearer, "fast")
    reader_headers, _ = user(api, bearer, "watch")
    slug = open_org(api, owner)
    api.client.post(f"/organizations/{slug}/join", headers=reader_headers, json={})
    org_id = api.client.get(f"/organizations/{slug}", headers=owner).json()["id"]
    topic = f"room:{org_id}"

    with (
        api.client.websocket_connect(f"/ws?ticket={ticket(api, owner)}") as typist,
        api.client.websocket_connect(
            f"/ws?ticket={ticket(api, reader_headers)}"
        ) as reader,
    ):
        for socket in (typist, reader):
            socket.send_json({"op": "subscribe", "topic": topic})
            assert socket.receive_json()["op"] == "subscribed"
        for _ in range(5):
            typist.send_json({"op": "typing", "topic": topic})
        # A ping round trip proves the typist's frames were all handled.
        typist.send_json({"op": "ping"})
        assert typist.receive_json() == {"op": "pong"}
        sent(api, owner, org_id, "Het")
        assert reader.receive_json()["type"] == "typing"
        assert reader.receive_json()["type"] == "message.created"
