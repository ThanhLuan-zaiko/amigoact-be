"""Realtime transport: ticket REST endpoint plus the /ws socket route."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from core.config import Settings, get_settings
from core.dependencies import CurrentUser, get_current_user
from core.dependencies_realtime import (
    get_connection_manager,
    get_realtime_service,
)
from core.exceptions import TooManyRequestsError
from core.realtime import (
    CLOSE_UNAUTHORIZED,
    ConnectionManager,
)
from core.realtime_heartbeat import heartbeat_loop
from realtime.frames import dispatch
from realtime.presence import fan_presence
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
    if not await asyncio.to_thread(service.user_is_active, user_id):
        logger.info("ws denied for non-active user %s", user_id)
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
            if not await dispatch(websocket, raw, state, service, manager, settings):
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
