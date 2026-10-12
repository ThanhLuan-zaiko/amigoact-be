"""Shared WebSocket plumbing: envelopes, channels, socket registry.

AGENTS.md 16.6: shared handshake/ticket code lives here (heartbeat sits
in core/realtime_heartbeat.py). The registry is ephemeral transport
state (16.5); business facts always replay from ScyllaDB on reconnect.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from fastapi import WebSocket
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger("amigoact.realtime")

# Application close codes (AGENTS.md 16.4).
CLOSE_BAD_FRAME = 4400
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_PONG_TIMEOUT = 4408

CHANNEL_KINDS = (
    "notifications", "attendance", "activities", "members", "orgs",
    "posts", "chat",
)

# Public kinds carry a fixed literal subject instead of a UUID.
PUBLIC_CHANNEL_SUBJECTS = {"orgs": "directory"}


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


class TypingFrame(SubscribeFrame):
    """Ephemeral typing ping for chat channels; relayed, never stored."""

    type: Literal["typing.v1"] = "typing.v1"


@dataclass(frozen=True)
class UnknownFrame:
    """Unrecognized type: logged and ignored, never crashes (16.4)."""

    frame_type: str


ClientFrame = (PingFrame | PongFrame | SubscribeFrame | UnsubscribeFrame
               | TypingFrame | UnknownFrame)

_FRAMES: dict[str, type[_Frame]] = {
    "ping.v1": PingFrame,
    "pong.v1": PongFrame,
    "subscribe.v1": SubscribeFrame,
    "unsubscribe.v1": UnsubscribeFrame,
    "typing.v1": TypingFrame,
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
    """Decode one frame; unknown types return UnknownFrame, malformed
    JSON or bad payloads raise BadFrameError (close 4400)."""
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
    """Parsed 'kind:{uuid}' name; public kinds get subject=None (16.3)."""

    kind: str
    subject: UUID | None


def parse_channel(raw: str) -> Channel | None:
    """Parse 'notifications:{uuid}' style names. None when malformed."""
    kind, sep, subject = raw.partition(":")
    if not sep or kind not in CHANNEL_KINDS:
        return None
    if kind in PUBLIC_CHANNEL_SUBJECTS:
        if subject != PUBLIC_CHANNEL_SUBJECTS[kind]:
            return None
        return Channel(kind=kind, subject=None)
    try:
        return Channel(kind=kind, subject=UUID(subject))
    except ValueError:
        return None


@dataclass
class ConnectionState:
    """One live socket: owner plus subscribed channels (ephemeral).

    user_id is None for anonymous guest sockets, which may only ever
    hold public channels per the service-level authorize() gate.
    on_offline fires if this socket turns out to be the user's last one.
    """

    websocket: WebSocket
    user_id: UUID | None
    channels: set[str] = field(default_factory=set)
    pong_pending: bool = False
    subscribe_times: list[float] = field(default_factory=list)
    frame_times: list[float] = field(default_factory=list)
    on_offline: Callable[[UUID], object] | None = None


class ConnectionManager:
    """In-process socket registry. Transport only, never a fact source."""

    def __init__(self) -> None:
        self._connections: dict[WebSocket, ConnectionState] = {}
        self._by_channel: dict[str, set[WebSocket]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        # user_id -> live socket count; presence transitions derive from it.
        self._online: dict[UUID, int] = {}
        # The loop keeps only weak task references; hold them until done.
        self._tasks: set[asyncio.Task[Any]] = set()

    def register(
        self,
        websocket: WebSocket,
        user_id: UUID | None,
        on_offline: Callable[[UUID], object] | None = None,
    ) -> ConnectionState:
        """Track a socket under its user id (None for guest sockets).

        Called from the async socket handler, so it also binds the app
        loop that schedule() needs for threadpool callers.
        """
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        state = ConnectionState(
            websocket=websocket, user_id=user_id, on_offline=on_offline
        )
        self._connections[websocket] = state
        if user_id is not None:
            self._online[user_id] = self._online.get(user_id, 0) + 1
        return state

    def unregister(self, websocket: WebSocket) -> None:
        """Drop a socket, its channels, and its presence share."""
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
        user_id = state.user_id
        if user_id is None:
            return
        remaining = self._online.get(user_id, 0) - 1
        if remaining > 0:
            self._online[user_id] = remaining
            return
        self._online.pop(user_id, None)
        if state.on_offline is not None:
            try:
                state.on_offline(user_id)
            except Exception:
                logger.debug("on_offline hook raised for %s", user_id)

    def is_online(self, user_id: UUID) -> bool:
        """True while at least one socket is bound to the user."""
        return self._online.get(user_id, 0) > 0

    def online_user_ids(self) -> set[UUID]:
        """Snapshot of every user with at least one live socket."""
        return set(self._online)

    def sockets_of(self, user_id: UUID) -> list[WebSocket]:
        """Every live socket bound to one user (snapshot list)."""
        return [
            s.websocket for s in self._connections.values() if s.user_id == user_id
        ]

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

    def schedule(self, coro: Coroutine[Any, Any, Any]) -> bool:
        """Run a coroutine on the app loop (or the caller's loop).

        Sync `def` endpoints run in the threadpool where no loop is
        running, so the work is scheduled onto the app loop bound at
        register() via run_coroutine_threadsafe. Callers with neither a
        running loop nor a bound one (scripts) get False and no attempt.
        """
        try:
            task = asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            pass
        else:
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return True
        loop = self._loop
        if loop is not None and not loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(coro, loop)
                return True
            except RuntimeError:
                pass
        coro.close()
        return False

    def schedule_publish(
        self, channel: str, payload: dict[str, Any] | None = None
    ) -> bool:
        """Fire-and-forget publish for sync callers."""
        return self.schedule(self.publish(channel, payload))
