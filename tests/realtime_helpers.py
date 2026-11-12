"""Shared steps for the realtime socket tests."""

from typing import Any

from starlette.testclient import WebSocketTestSession

from tests.activity_helpers import Headers
from tests.conftest import ApiContext


def realtime_ticket(api: ApiContext, headers: Headers) -> str:
    response = api.client.post("/realtime/tickets", headers=headers)
    assert response.status_code == 201, response.text
    value: str = response.json()["ticket"]
    return value


def org_id_of(api: ApiContext, slug: str, headers: Headers) -> str:
    value: str = api.client.get(f"/organizations/{slug}", headers=headers).json()["id"]
    return value


def subscribe(socket: WebSocketTestSession, topic: str) -> dict[str, Any]:
    socket.send_json({"op": "subscribe", "topic": topic})
    reply: dict[str, Any] = socket.receive_json()
    return reply


def frames_until_pong(socket: WebSocketTestSession) -> list[dict[str, Any]]:
    """Everything pushed before this ping. Pushes from a finished request come first."""
    socket.send_json({"op": "ping"})
    frames = []
    while (frame := socket.receive_json()) != {"op": "pong"}:
        frames.append(frame)
    return frames


def event_types(frames: list[dict[str, Any]], topic: str) -> list[str]:
    return [frame["type"] for frame in frames if frame.get("topic") == topic]
