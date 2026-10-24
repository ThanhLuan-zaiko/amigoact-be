"""Client-frame handlers for the /ws loop (split from router, 4 line cap)."""

from __future__ import annotations

import asyncio
import logging
import time
from uuid import UUID

from fastapi import WebSocket

from core.config import Settings
from core.realtime import (
    CLOSE_BAD_FRAME,
    CLOSE_FORBIDDEN,
    BadFrameError,
    ConnectionManager,
    ConnectionState,
    PingFrame,
    PongFrame,
    SubscribeFrame,
    TypingFrame,
    UnknownFrame,
    UnsubscribeFrame,
    parse_channel,
    parse_client_frame,
)
from realtime.presence import read_roster, send_presence_snapshot
from realtime.service import RealtimeService

logger = logging.getLogger("amigoact.realtime")


async def dispatch(
    websocket: WebSocket,
    raw: str,
    state: ConnectionState,
    service: RealtimeService,
    manager: ConnectionManager,
    settings: Settings,
) -> bool:
    """Route one client frame. Returns False when the socket must close."""
    if len(raw) > settings.ws_max_frame_bytes:
        await manager.send(
            websocket,
            "error.v1",
            {"code": "BAD_FRAME", "message": "Frame exceeds the size limit."},
        )
        await websocket.close(code=CLOSE_BAD_FRAME)
        return False
    now = time.monotonic()
    state.frame_times = [t for t in state.frame_times if now - t < 1.0]
    if len(state.frame_times) >= settings.ws_frame_per_sec:
        await manager.send(
            websocket,
            "error.v1",
            {"code": "TOO_MANY_REQUESTS", "message": "Frame rate exceeded."},
        )
        return True
    state.frame_times.append(now)
    try:
        frame = parse_client_frame(raw)
    except BadFrameError as exc:
        await manager.send(
            websocket,
            "error.v1",
            {"code": "BAD_FRAME", "message": str(exc)},
        )
        await websocket.close(code=CLOSE_BAD_FRAME)
        return False
    if isinstance(frame, UnknownFrame):
        logger.debug("ws: ignored unknown frame type %r", frame.frame_type)
        return True
    if isinstance(frame, PongFrame):
        state.pong_pending = False
        return True
    if isinstance(frame, PingFrame):
        await manager.send(websocket, "pong.v1", {})
        return True
    if isinstance(frame, UnsubscribeFrame):
        return await _unsubscribe(websocket, frame, manager)
    if isinstance(frame, TypingFrame):
        return await _typing(websocket, frame, state, service, manager)
    if isinstance(frame, SubscribeFrame):
        return await _subscribe(websocket, frame, state, service, manager)
    return True


async def _typing(
    websocket: WebSocket,
    frame: TypingFrame,
    state: ConnectionState,
    service: RealtimeService,
    manager: ConnectionManager,
) -> bool:
    """Relay an ephemeral typing ping onto a chat:{org} channel.

    Membership is re-checked per frame (guests and non-members get a quiet
    error, never a close). The relay only marks the sender; receivers use
    it as a transient hint, not a fact source.
    """
    name = frame.channel_name
    if name is None or state.user_id is None:
        return True
    channel = parse_channel(name)
    if channel is None or channel.kind != "chat":
        return True
    allowed = await asyncio.to_thread(
        service.authorize, channel, state.user_id
    )
    if not allowed:
        await manager.send(
            websocket,
            "error.v1",
            {"code": "FORBIDDEN", "message": "Channel is not allowed.",
             "channel": name},
        )
        return True
    await manager.publish(
        name, {"action": "typing", "user_id": str(state.user_id)}
    )
    return True


async def _subscribe(
    websocket: WebSocket,
    frame: SubscribeFrame,
    state: ConnectionState,
    service: RealtimeService,
    manager: ConnectionManager,
) -> bool:
    """Authorize then join a channel. Denials close 4403."""
    now = time.monotonic()
    state.subscribe_times = [t for t in state.subscribe_times if now - t < 60.0]
    if len(state.subscribe_times) >= 20:
        await manager.send(
            websocket,
            "error.v1",
            {"code": "TOO_MANY_REQUESTS", "message": "Subscribe rate exceeded."},
        )
        return True
    state.subscribe_times.append(now)
    name = frame.channel_name
    if name is None:
        return await _bad_frame(
            websocket, manager, "subscribe.v1 requires data.channel."
        )
    channel = parse_channel(name)
    if channel is None:
        await manager.send(
            websocket,
            "error.v1",
            {
                "code": "INVALID_CHANNEL",
                "message": "Unknown or malformed channel.",
                "channel": name,
            },
        )
        return True
    allowed = await asyncio.to_thread(service.authorize, channel, state.user_id)
    if not allowed:
        await manager.send(
            websocket,
            "error.v1",
            {
                "code": "FORBIDDEN",
                "message": "Channel is not allowed.",
                "channel": name,
            },
        )
        await websocket.close(code=CLOSE_FORBIDDEN)
        return False
    # First-time members:{org} joins get the online roster snapshot so
    # clients render presence without waiting for the next transition.
    # The roster is read before joining: no DB wait separates
    # subscribed.v1 from the snapshot.
    roster: list[UUID] | None = None
    if (
        channel.kind == "members"
        and channel.subject is not None
        and state.user_id is not None
        and name not in state.channels
    ):
        roster = await read_roster(service, channel.subject)
    joined = manager.subscribe(websocket, name)
    await manager.send(
        websocket,
        "subscribed.v1",
        {"channel": name, "channels": sorted(state.channels)},
    )
    if joined and roster is not None:
        await send_presence_snapshot(manager, websocket, name, roster)
    return True


async def _unsubscribe(
    websocket: WebSocket,
    frame: UnsubscribeFrame,
    manager: ConnectionManager,
) -> bool:
    """Leave a channel; unknown names are acknowledged quietly."""
    name = frame.channel_name
    if name is None:
        return await _bad_frame(
            websocket, manager, "unsubscribe.v1 requires data.channel."
        )
    if manager.unsubscribe(websocket, name):
        await manager.send(websocket, "unsubscribed.v1", {"channel": name})
    return True


async def _bad_frame(
    websocket: WebSocket, manager: ConnectionManager, message: str
) -> bool:
    """Emit error.v1 then close 4400 for malformed known frames."""
    await manager.send(websocket, "error.v1", {"code": "BAD_FRAME", "message": message})
    await websocket.close(code=CLOSE_BAD_FRAME)
    return False
