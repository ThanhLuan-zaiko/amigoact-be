"""Open sockets and the rooms each one listens to. Lives in one process, so messages reach the sockets of this process."""

import uuid
from typing import Any

import anyio
from starlette.websockets import WebSocket, WebSocketDisconnect


class ChatHub:
    def __init__(self) -> None:
        self._rooms: dict[uuid.UUID, set[WebSocket]] = {}
        self._owners: dict[WebSocket, uuid.UUID] = {}

    def register(self, socket: WebSocket, user_id: uuid.UUID) -> None:
        self._owners[socket] = user_id

    def unregister(self, socket: WebSocket) -> None:
        self._owners.pop(socket, None)
        for listeners in self._rooms.values():
            listeners.discard(socket)

    def subscribe(self, room_id: uuid.UUID, socket: WebSocket) -> None:
        self._rooms.setdefault(room_id, set()).add(socket)

    def unsubscribe(self, room_id: uuid.UUID, socket: WebSocket) -> None:
        self._rooms.get(room_id, set()).discard(socket)

    def has_listeners(self, room_id: uuid.UUID) -> bool:
        return bool(self._rooms.get(room_id))

    async def broadcast(self, room_id: uuid.UUID, event: dict[str, Any]) -> None:
        for socket in list(self._rooms.get(room_id, ())):
            await _send(self, socket, event)

    async def revoke(self, room_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Stop one person's sockets from hearing a room they may no longer enter."""
        for socket in list(self._rooms.get(room_id, ())):
            if self._owners.get(socket) == user_id:
                self.unsubscribe(room_id, socket)
                await _send(self, socket, {"op": "revoked", "room_id": str(room_id)})


async def _send(hub: ChatHub, socket: WebSocket, event: dict[str, Any]) -> None:
    try:
        await socket.send_json(event)
    except RuntimeError, WebSocketDisconnect:
        hub.unregister(socket)


hub = ChatHub()


def publish(room_id: uuid.UUID, event: dict[str, Any]) -> None:
    """Called from the sync request handlers, which run in worker threads."""
    if not hub.has_listeners(room_id):
        return
    anyio.from_thread.run(hub.broadcast, room_id, event)


def revoke(room_id: uuid.UUID, user_id: uuid.UUID) -> None:
    if not hub.has_listeners(room_id):
        return
    anyio.from_thread.run(hub.revoke, room_id, user_id)
