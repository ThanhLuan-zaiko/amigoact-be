"""Server heartbeat coroutine for live WebSocket connections.

Split from core/realtime.py so the registry module stays under the
AGENTS.md file-size budget; behavior is unchanged.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket

from core.realtime import CLOSE_PONG_TIMEOUT, ConnectionManager
from core.security import utcnow

logger = logging.getLogger("amigoact.realtime")


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
