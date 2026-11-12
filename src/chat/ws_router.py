"""The chat socket: a one-time ticket in, then subscribe and unsubscribe to rooms."""

import uuid
from typing import Any

import anyio
from fastapi import APIRouter, Query, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocket, WebSocketDisconnect

from src.auth.deps import CurrentPrincipal, Db
from src.chat.hub import hub
from src.chat.rooms import readable_by
from src.chat.rules import SOCKET_LIFETIME_SECONDS
from src.chat.schemas import TicketResponse
from src.chat.tickets import consume_ticket, issue_ticket
from src.cors import get_cors_settings, origin_allowed

router = APIRouter(tags=["chat"])

UNAUTHORIZED_CLOSE = 4401
EXPIRED_CLOSE = 4408
FORBIDDEN_ORIGIN_CLOSE = 4403


@router.post("/chat/tickets", status_code=status.HTTP_201_CREATED)
def create_ticket(principal: CurrentPrincipal, db: Db) -> TicketResponse:
    return issue_ticket(db, principal.user.id)


def _can_read(engine: Any, room_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    with Session(engine) as db:
        return readable_by(db, room_id, user_id)


async def _reply(socket: WebSocket, body: dict[str, Any]) -> None:
    await socket.send_json(body)


async def _handle(
    socket: WebSocket, engine: Any, user_id: uuid.UUID, frame: object
) -> None:
    if not isinstance(frame, dict):
        await _reply(socket, {"op": "error", "code": "bad_frame"})
        return
    op = frame.get("op")
    if op == "ping":
        await _reply(socket, {"op": "pong"})
        return
    if op not in ("subscribe", "unsubscribe"):
        await _reply(socket, {"op": "error", "code": "unknown_op"})
        return
    try:
        room_id = uuid.UUID(str(frame.get("room_id")))
    except ValueError:
        await _reply(socket, {"op": "error", "code": "room_id_invalid"})
        return
    if op == "unsubscribe":
        hub.unsubscribe(room_id, socket)
        await _reply(socket, {"op": "unsubscribed", "room_id": str(room_id)})
        return
    # Checked on every subscribe, so a room that was closed or left cannot be joined again.
    allowed = await run_in_threadpool(_can_read, engine, room_id, user_id)
    if not allowed:
        await _reply(socket, {"op": "error", "code": "room_not_found"})
        return
    hub.subscribe(room_id, socket)
    await _reply(socket, {"op": "subscribed", "room_id": str(room_id)})


@router.websocket("/ws/chat")
async def chat_socket(websocket: WebSocket, ticket: str = Query(default="")) -> None:
    # CORS does not cover sockets, so a page on another site is refused here,
    # before its ticket is spent.
    if not origin_allowed(websocket.headers.get("origin"), get_cors_settings().origins):
        await websocket.close(code=FORBIDDEN_ORIGIN_CLOSE)
        return
    engine = websocket.app.state.engine
    user_id = await run_in_threadpool(consume_ticket, engine, ticket)
    if user_id is None:
        await websocket.close(code=UNAUTHORIZED_CLOSE)
        return
    await websocket.accept()
    hub.register(websocket, user_id)
    try:
        # A session ends after its lifetime, so access is rechecked on a fresh ticket.
        with anyio.move_on_after(SOCKET_LIFETIME_SECONDS) as scope:
            while True:
                try:
                    frame = await websocket.receive_json()
                except ValueError:
                    await _reply(websocket, {"op": "error", "code": "bad_frame"})
                    continue
                await _handle(websocket, engine, user_id, frame)
        if scope.cancelled_caught:
            await websocket.close(code=EXPIRED_CLOSE)
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(websocket)
