"""Open sockets of this process and the topics each one listens to."""

import uuid
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from src.realtime.names import ROOM, parse_topic, user_topic


class Hub:
    def __init__(self) -> None:
        self._topics: dict[str, set[WebSocket]] = {}
        self._owners: dict[WebSocket, uuid.UUID] = {}

    def register(self, socket: WebSocket, user_id: uuid.UUID) -> None:
        """A socket always hears its owner's own topic."""
        self._owners[socket] = user_id
        self.subscribe(user_topic(user_id), socket)

    def unregister(self, socket: WebSocket) -> None:
        self._owners.pop(socket, None)
        for listeners in self._topics.values():
            listeners.discard(socket)

    def subscribe(self, topic: str, socket: WebSocket) -> None:
        self._topics.setdefault(topic, set()).add(socket)

    def unsubscribe(self, topic: str, socket: WebSocket) -> None:
        self._topics.get(topic, set()).discard(socket)

    def is_subscribed(self, topic: str, socket: WebSocket) -> bool:
        return socket in self._topics.get(topic, ())

    def has_listeners(self, topic: str) -> bool:
        return bool(self._topics.get(topic))

    def is_online(self, user_id: uuid.UUID) -> bool:
        return self.has_listeners(user_topic(user_id))

    async def broadcast(self, topic: str, event: dict[str, Any]) -> None:
        body = {**event, "topic": topic}
        for socket in list(self._topics.get(topic, ())):
            await self._send(socket, body)

    async def broadcast_except(
        self, topic: str, event: dict[str, Any], user_id: uuid.UUID
    ) -> None:
        """Every listener except the sockets of one person, who knows what they did."""
        body = {**event, "topic": topic}
        for socket in list(self._topics.get(topic, ())):
            if self._owners.get(socket) != user_id:
                await self._send(socket, body)

    async def revoke(self, topics: list[str], user_id: uuid.UUID) -> None:
        """Stop one person's sockets from hearing topics they may no longer read."""
        for topic in topics:
            for socket in list(self._topics.get(topic, ())):
                if self._owners.get(socket) == user_id:
                    self.unsubscribe(topic, socket)
                    await self._send(socket, revoked_frame(topic))

    async def _send(self, socket: WebSocket, body: dict[str, Any]) -> None:
        try:
            await socket.send_json(body)
        except RuntimeError, WebSocketDisconnect:
            self.unregister(socket)


def revoked_frame(topic: str) -> dict[str, Any]:
    """Room topics also carry room_id, the field older chat clients read."""
    frame: dict[str, Any] = {"op": "revoked", "topic": topic}
    parsed = parse_topic(topic)
    if parsed is not None and parsed[0] == ROOM:
        frame["room_id"] = str(parsed[1])
    return frame


hub = Hub()
