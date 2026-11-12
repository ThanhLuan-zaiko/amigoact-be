"""The typing signal through the socket."""

from typing import Any

from tests.activity_helpers import Bearer, user
from tests.chat_helpers import sent, ticket
from tests.conftest import ApiContext
from tests.post_helpers import join, open_org


def test_typing_reaches_others_in_the_room_but_not_the_typist(
    api: ApiContext, bearer: Bearer
) -> None:
    owner, owner_id = user(api, bearer, "typist")
    member, _ = user(api, bearer, "reader")
    slug = open_org(api, owner)
    join(api, slug, member)
    org_id = api.client.get(f"/organizations/{slug}", headers=owner).json()["id"]
    topic = f"room:{org_id}"

    with (
        api.client.websocket_connect(f"/ws?ticket={ticket(api, owner)}") as typist,
        api.client.websocket_connect(f"/ws?ticket={ticket(api, member)}") as reader,
    ):
        for socket in (typist, reader):
            socket.send_json({"op": "subscribe", "topic": topic})
            assert socket.receive_json()["op"] == "subscribed"

        typist.send_json({"op": "typing", "topic": topic})
        heard: dict[str, Any] = reader.receive_json()
        assert heard == {
            "type": "typing",
            "room_id": org_id,
            "user_id": owner_id,
            "name": "Test User",
            "topic": topic,
        }
        # The typist's own socket hears the next real event, not its own signal.
        sent(api, owner, org_id, "Xong")
        assert typist.receive_json()["type"] == "message.created"
        assert reader.receive_json()["type"] == "message.created"
