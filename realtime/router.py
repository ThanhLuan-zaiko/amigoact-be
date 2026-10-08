"""Realtime transport: ticket REST endpoint plus the /ws socket route."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from core.config import Settings, get_settings
from core.dependencies import (
    CurrentUser,
    get_connection_manager,
    get_current_user,
    get_realtime_service,
)
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
    heartbeat_loop,
    parse_channel,
    parse_client_frame,
)
from realtime.schemas import WsTicketResponse
from realtime.service import RealtimeService

logger = logging.getLogger("amigoact.realtime")

router = APIRouter(tags=["realtime"])


@router.post("/ws/tickets", response_model=WsTicketResponse, status_code=201)
def issue_ticket(
    current: CurrentUser = Depends(get_current_user),
    service: RealtimeService = Depends(get_realtime_service),
) -> WsTicketResponse:
    """Mint a one-time WS handshake ticket bound to the current user."""
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
    """Bind a one-time ticket to a socket, then serve frames (16)."""
    await websocket.accept()
    user_id = await asyncio.to_thread(service.consume_ticket, ticket)
    if user_id is None:
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return
    await _serve(websocket, user_id, service, manager, settings)


async def _serve(
    websocket: WebSocket,
    user_id,
    service: RealtimeService,
    manager: ConnectionManager,
    settings: Settings,
) -> None:
    """Frame loop for one authenticated socket until disconnect."""
    state = manager.register(websocket, user_id)
    manager.subscribe(websocket, f"notifications:{user_id}")
    await manager.send(
        websocket,
        "ready.v1",
        {
            "user_id": str(user_id),
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
    try:
        while True:
            raw = await websocket.receive_text()
            if not await _dispatch(websocket, raw, state, service, manager):
                break
    except WebSocketDisconnect:
        pass
    finally:
        heartbeat.cancel()
        manager.unregister(websocket)


async def _dispatch(
    websocket: WebSocket,
    raw: str,
    state: ConnectionState,
    service: RealtimeService,
    manager: ConnectionManager,
) -> bool:
    """Route one client frame. Returns False when the socket must close."""
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
        logger.info("ws: ignored unknown frame type %r", frame.frame_type)
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
    manager.subscribe(websocket, name)
    await manager.send(
        websocket,
        "subscribed.v1",
        {"channel": name, "channels": sorted(state.channels)},
    )
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
