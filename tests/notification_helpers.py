"""Shared steps for the live notification tests."""

from typing import Any

from starlette.testclient import WebSocketTestSession

from tests.activity_helpers import Headers
from tests.conftest import ApiContext


def apply(api: ApiContext, slug: str, headers: Headers, message: str | None) -> Any:
    body = {"message": message} if message else {}
    return api.client.post(f"/organizations/{slug}/join", headers=headers, json=body)


def make_admin(
    api: ApiContext, owner: Headers, slug: str, headers: Headers, user_id: str
) -> None:
    apply(api, slug, headers, None)
    base = f"/organizations/{slug}"
    approved = api.client.post(f"{base}/applications/{user_id}/approve", headers=owner)
    assert approved.status_code == 204, approved.text
    promoted = api.client.patch(
        f"{base}/members/{user_id}", headers=owner, json={"role": "admin"}
    )
    assert promoted.status_code == 204, promoted.text


# Page refresh signals ride along on the same sockets; these tests look past them.
SIGNALS = {"members.changed", "applications.changed", "membership.changed"}


def _relevant(frame: dict[str, Any]) -> bool:
    return frame.get("type") not in SIGNALS


def next_frame(socket: WebSocketTestSession) -> dict[str, Any]:
    """The first notification or revoke frame pushed before a ping, or pong if none.

    The topic field is left out, so a test can compare the rest exactly.
    """
    socket.send_json({"op": "ping"})
    found: dict[str, Any] | None = None
    while (frame := socket.receive_json()) != {"op": "pong"}:
        if found is None and _relevant(frame):
            found = {key: value for key, value in frame.items() if key != "topic"}
    return found or {"op": "pong"}


def heard_nothing(socket: WebSocketTestSession) -> bool:
    return next_frame(socket) == {"op": "pong"}
