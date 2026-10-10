"""Shared WebSocket plumbing: envelopes, channels, registry, heartbeat.

AGENTS.md 16.6: shared handshake/ticket/heartbeat code lives here only.
The registry is ephemeral transport state (16.5) - never authoritative;
business facts always replay from ScyllaDB after reconnect.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from fastapi import WebSocket
from pydantic import BaseModel, Field, ValidationError

from core.security import utcnow

logger = logging.getLogger("amigoact.realtime")

# Application close codes (AGENTS.md 16.4).
CLOSE_BAD_FRAME = 4400
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_PONG_TIMEOUT = 4408

CHANNEL_KINDS = ("notifications", "attendance", "activities", "members")


class BadFrameError(Exception):
    """Raised when a client frame is not a valid {type, data} envelope."""


class _Frame(BaseModel):
    """Every client frame carries a versioned type plus a data object."""

    type: str
    data: dict[str, Any] = Field(default_factory=dict)


class PingFrame(_Frame):
    """Client liveness probe; the server answers with pong.v1."""

    type: Literal["ping.v1"] = "ping.v1"


class PongFrame(_Frame):
    """Client answer to the server heartbeat ping."""

    type: Literal["pong.v1"] = "pong.v1"


class SubscribeFrame(_Frame):
    """Channel join request, authorized per 8 before subscribing."""

    type: Literal["subscribe.v1"] = "subscribe.v1"

    @property
    def channel_name(self) -> str | None:
        """data.channel as a non-empty string, or None when malformed."""
        value = self.data.get("channel")
        return value if isinstance(value, str) and value else None


class UnsubscribeFrame(SubscribeFrame):
    """Channel leave request for an already subscribed channel."""

    type: Literal["unsubscribe.v1"] = "unsubscribe.v1"


@dataclass(frozen=True)
class UnknownFrame:
    """Unrecognized type: logged and ignored, never crashes (16.4)."""

    frame_type: str


ClientFrame = PingFrame | PongFrame | SubscribeFrame | UnsubscribeFrame | UnknownFrame

_FRAMES: dict[str, type[_Frame]] = {
    "ping.v1": PingFrame,
    "pong.v1": PongFrame,
    "subscribe.v1": SubscribeFrame,
    "unsubscribe.v1": UnsubscribeFrame,
}


def encode_envelope(
    frame_type: str, data: dict[str, Any] | BaseModel | None = None
) -> str:
    """Serialize a server frame as {"type": "<name>", "data": {...}}."""
    body = (
        data.model_dump(mode="json")
        if isinstance(data, BaseModel)
        else (data or {})
    )
    return json.dumps({"type": frame_type, "data": body})


def parse_client_frame(raw: str) -> ClientFrame:
    """Decode one client frame.

    Unknown types return UnknownFrame (ignored upstream). Malformed JSON
    or invalid known-type payloads raise BadFrameError (close 4400).
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BadFrameError("Frame must be a JSON object.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("type"), str):
        raise BadFrameError("Frame must carry a string type.")
    data = payload.get("data", {})
    if not isinstance(data, dict):
        raise BadFrameError("Frame data must be an object.")
    model = _FRAMES.get(payload["type"])
    if model is None:
        return UnknownFrame(payload["type"])
    try:
        return model(type=payload["type"], data=data)
    except ValidationError as exc:
        raise BadFrameError("Frame payload failed validation.") from exc


@dataclass(frozen=True)
class Channel:
    """Parsed 'kind:{uuid}' channel name (AGENTS.md 16.3)."""

    kind: str
    subject: UUID


def parse_channel(raw: str) -> Channel | None:
    """Parse 'notifications:{uuid}' style names. None when malformed."""
    kind, sep, subject = raw.partition(":")
    if not sep or kind not in CHANNEL_KINDS:
        return None
    try:
        return Channel(kind=kind, subject=UUID(subject))
    except ValueError:
        return None


@dataclass
class ConnectionState:
    """One live socket: owner plus subscribed channels (ephemeral)."""

    websocket: WebSocket
    user_id: UUID
    channels: set[str] = field(default_factory=set)
    pong_pending: bool = False
    subscribe_times: list[float] = field(default_factory=list)
    frame_times: list[float] = field(default_factory=list)


class ConnectionManager:
    """In-process socket registry. Transport only, never a fact source."""

    def __init__(self) -> None:
        self._connections: dict[WebSocket, ConnectionState] = {}
        self._by_channel: dict[str, set[WebSocket]] = {}

    def register(self, websocket: WebSocket, user_id: UUID) -> ConnectionState:
        """Track an authenticated socket under its user id."""
        state = ConnectionState(websocket=websocket, user_id=user_id)
        self._connections[websocket] = state
        return state

    def unregister(self, websocket: WebSocket) -> None:
        """Drop a socket and all of its channel subscriptions."""
        state = self._connections.pop(websocket, None)
        if state is None:
            return
        for channel in state.channels:
            sockets = self._by_channel.get(channel)
            if sockets is None:
                continue
            sockets.discard(websocket)
            if not sockets:
                del self._by_channel[channel]

    def state_of(self, websocket: WebSocket) -> ConnectionState | None:
        """Live state for one socket, or None once unregistered."""
        return self._connections.get(websocket)

    def subscribe(self, websocket: WebSocket, channel: str) -> bool:
        """Add a channel to a socket. False when already subscribed."""
        state = self._connections.get(websocket)
        if state is None or channel in state.channels:
            return False
        state.channels.add(channel)
        self._by_channel.setdefault(channel, set()).add(websocket)
        return True

    def unsubscribe(self, websocket: WebSocket, channel: str) -> bool:
        """Remove a channel from a socket. False when not subscribed."""
        state = self._connections.get(websocket)
        if state is None or channel not in state.channels:
            return False
        state.channels.discard(channel)
        sockets = self._by_channel.get(channel)
        if sockets is not None:
            sockets.discard(websocket)
            if not sockets:
                del self._by_channel[channel]
        return True

    async def send(
        self,
        websocket: WebSocket,
        frame_type: str,
        data: dict[str, Any] | BaseModel | None = None,
    ) -> None:
        """Send one encoded envelope to a single socket."""
        await websocket.send_text(encode_envelope(frame_type, data))

    async def publish(
        self, channel: str, payload: dict[str, Any] | None = None
    ) -> int:
        """Fan one event.v1 frame to a channel. Returns delivered count."""
        sockets = list(self._by_channel.get(channel, ()))
        if not sockets:
            return 0

        async def _send_one(websocket: WebSocket) -> bool:
            try:
                await asyncio.wait_for(
                    self.send(
                        websocket,
                        "event.v1",
                        {"channel": channel, "payload": payload or {}},
                    ),
                    timeout=2.0,
                )
                return True
            except Exception:
                logger.debug("publish dropped dead socket on %s", channel)
                return False

        results = await asyncio.gather(*(_send_one(ws) for ws in sockets))
        delivered = 0
        for websocket, ok in zip(sockets, results):
            if ok:
                delivered += 1
            else:
                self.unregister(websocket)
        return delivered

    def schedule_publish(
        self, channel: str, payload: dict[str, Any] | None = None
    ) -> bool:
        """Fire-and-forget publish for sync callers inside the loop.

        Member mutations run in sync services called from async
        endpoints, so they cannot await publish(); the send is queued
        on the running loop instead. Callers without a running loop
        (unit tests, scripts) get False and no delivery attempt.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False
        loop.create_task(self.publish(channel, payload))
        return True


async def heartbeat_loop(
    manager: ConnectionManager,
    websocket: WebSocket,
    interval_seconds: int,
    pong_timeout_seconds: int,
) -> None:
    """Server heartbeat: ping.v1 per cycle, close 4408 on missed pong.

    Each cycle sleeps interval_seconds, pings, then grants the client
    pong_timeout_seconds to answer before closing the socket.
    """
    if interval_seconds < 1 or pong_timeout_seconds < 1:
        return
    try:
        while True:
            await asyncio.sleep(interval_seconds)
            state = manager.state_of(websocket)
            if state is None:
                return
            state.pong_pending = True
            try:
                await manager.send(
                    websocket, "ping.v1", {"ts": utcnow().isoformat()}
                )
            except Exception:
                return
            await asyncio.sleep(pong_timeout_seconds)
            state = manager.state_of(websocket)
            if state is None:
                return
            if state.pong_pending:
                try:
                    await websocket.close(code=CLOSE_PONG_TIMEOUT)
                except Exception:
                    pass
                return
    except asyncio.CancelledError:
        return
