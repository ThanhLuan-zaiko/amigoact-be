"""Realtime transport: ticket REST endpoint plus the /ws socket route."""

from __future__ import annotations

import asyncio
import logging
import time
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from core.config import Settings, get_settings
from core.dependencies import (
    CurrentUser,
    get_connection_manager,
    get_current_user,
    get_realtime_service,
)
from core.exceptions import TooManyRequestsError
from core.realtime import (
    CLOSE_BAD_FRAME,
    CLOSE_FORBIDDEN,
    CLOSE_UNAUTHORIZED,
    BadFrameError,
    ConnectionManager,
    ConnectionState,
    PingFrame,
    PongFrame,
    SubscribeFrame,
    UnknownFrame,
    UnsubscribeFrame,
    parse_channel,
    parse_client_frame,
)
from core.realtime_heartbeat import heartbeat_loop
from realtime.presence import fan_presence, read_roster, send_presence_snapshot
from realtime.schemas import WsTicketResponse
from realtime.service import RealtimeService

logger = logging.getLogger("amigoact.realtime")

router = APIRouter(tags=["realtime"])


@router.post("/ws/tickets", response_model=WsTicketResponse, status_code=201)
def issue_ticket(
    current: CurrentUser = Depends(get_current_user),
    service: RealtimeService = Depends(get_realtime_service),
    settings: Settings = Depends(get_settings),
) -> WsTicketResponse:
    """Mint a one-time WS handshake ticket bound to the current user."""
    try:
        from auth.repository import CqlRateLimiter

        hits = CqlRateLimiter(settings.scylla_keyspace).hit(
            f"ws_ticket:{current.id}", 60
        )
        if hits > settings.ws_ticket_per_min:
            raise TooManyRequestsError("Too many ticket requests.")
    except TooManyRequestsError:
        raise
    except Exception as exc:
        logger.warning("ws ticket rate-limit unavailable: %s", exc)
    issued = service.issue_ticket(current.id)
    return WsTicketResponse(ticket=issued.token, expires_in=issued.expires_in)


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    ticket: str = "",
    service: RealtimeService = Depends(get_realtime_service),
    manager: ConnectionManager = Depends(get_connection_manager),
    settings: Settings = Depends(get_settings),
) -> None:
    """Bind a one-time ticket to a socket, then serve frames (16).

    A missing ticket opens an anonymous guest socket that may only
    subscribe to public channels; a present-but-invalid ticket still
    closes 4401 so bad credentials are never silently downgraded.
    """
    await websocket.accept()
    if not ticket or not ticket.strip():
        await _serve(websocket, None, service, manager, settings)
        return
    user_id = await asyncio.to_thread(service.consume_ticket, ticket)
    if user_id is None:
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return
    if not await _require_active_user(user_id, settings, websocket):
        return
    await _serve(websocket, user_id, service, manager, settings)


async def _require_active_user(user_id, settings: Settings, websocket: WebSocket) -> bool:
    """Reject suspended or deleted users after ticket consume (AGENTS.md 8).

    TODO: inject a UserLookup port into RealtimeService to avoid importing
    the auth repository here; router-level check keeps service DIP-clean.
    """
    try:
        from auth.repository import CqlUserRepository

        user = await asyncio.to_thread(
            CqlUserRepository(settings.scylla_keyspace).get_by_id, user_id
        )
    except Exception as exc:
        logger.warning("ws user lookup unavailable, allowing: %s", exc)
        return True
    if user is None or getattr(user, "status", "active") != "active":
        try:
            await websocket.close(code=CLOSE_UNAUTHORIZED)
        except Exception:
            pass
        return False
    return True


async def _serve(
    websocket: WebSocket,
    user_id,
    service: RealtimeService,
    manager: ConnectionManager,
    settings: Settings,
) -> None:
    """Frame loop for one socket until disconnect (user_id may be None)."""
    was_online = user_id is not None and manager.is_online(user_id)
    # This socket's own service fans the offline state out if it is the
    # user's last one (scheduled: it may fire inside publish()).
    state = manager.register(
        websocket,
        user_id,
        on_offline=lambda uid: manager.schedule(fan_presence(manager, service, uid)),
    )
    heartbeat: asyncio.Task[None] | None = None
    try:
        if user_id is not None:
            manager.subscribe(websocket, f"notifications:{user_id}")
            if not was_online:
                # Awaited before ready.v1: the client has joined no roster
                # channel yet, so it never sees its own transition ahead of
                # a members:{org} snapshot.
                await fan_presence(manager, service, user_id)
        await manager.send(
            websocket,
            "ready.v1",
            {
                "user_id": str(user_id) if user_id is not None else None,
                "channels": sorted(state.channels),
                "heartbeat_seconds": settings.ws_heartbeat_seconds,
            },
        )
        heartbeat = asyncio.create_task(
            heartbeat_loop(
                manager,
                websocket,
                settings.ws_heartbeat_seconds,
                settings.ws_pong_timeout_seconds,
            )
        )
        while True:
            raw = await websocket.receive_text()
            if not await _dispatch(websocket, raw, state, service, manager, settings):
                break
    except WebSocketDisconnect:
        pass
    finally:
        if heartbeat is not None:
            heartbeat.cancel()
            try:
                await heartbeat
            except (asyncio.CancelledError, Exception):
                pass
        manager.unregister(websocket)


async def _dispatch(
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
    if isinstance(frame, SubscribeFrame):
        return await _subscribe(websocket, frame, state, service, manager)
    return True


async def _subscribe(
    websocket: WebSocket,
    frame: SubscribeFrame,
    state: ConnectionState,
    service: RealtimeService,
    manager: ConnectionManager,
) -> bool:
    """Authorize then join a channel. Denials close 4403 (16.4)."""
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
    await manager.send(
        websocket, "error.v1", {"code": "BAD_FRAME", "message": message}
    )
    await websocket.close(code=CLOSE_BAD_FRAME)
    return False
