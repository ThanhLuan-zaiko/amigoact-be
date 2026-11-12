"""The one socket: a one-time ticket in, then subscribe and unsubscribe to topics.

/ws/chat and POST /chat/tickets stay as aliases, and a frame with room_id still
means the room topic, so older chat clients keep working.
"""

import uuid
from typing import Any

import anyio
from fastapi import APIRouter, Query, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocket, WebSocketDisconnect

from src.auth.deps import CurrentPrincipal, Db
from src.chat.rules import SOCKET_LIFETIME_SECONDS
from src.chat.schemas import TicketResponse
from src.chat.tickets import consume_ticket, issue_ticket
from src.cors import get_cors_settings, origin_allowed
from src.realtime.access import can_listen
from src.realtime.hub import hub
from src.realtime.names import USER, parse_topic, room_topic

router = APIRouter(tags=["realtime"])

UNAUTHORIZED_CLOSE = 4401
EXPIRED_CLOSE = 4408
FORBIDDEN_ORIGIN_CLOSE = 4403


@router.post("/realtime/tickets", status_code=status.HTTP_201_CREATED)
@router.post("/chat/tickets", status_code=status.HTTP_201_CREATED)
def create_ticket(principal: CurrentPrincipal, db: Db) -> TicketResponse:
    return issue_ticket(db, principal.user.id)


def _allowed(engine: Any, topic: str, user_id: uuid.UUID) -> bool:
    with Session(engine) as db:
        return can_listen(db, topic, user_id)


def _requested_topic(frame: dict[str, Any]) -> tuple[str | None, bool]:
    """The topic a frame names, and whether it used the older room_id field."""
    if "topic" in frame:
        topic = frame.get("topic")
        return (topic if parse_topic(topic) else None), False
    try:
        return room_topic(uuid.UUID(str(frame.get("room_id")))), True
    except ValueError:
        return None, True


def _reply(op: str, topic: str, legacy: bool) -> dict[str, Any]:
    if legacy:
        return {"op": op, "room_id": topic.partition(":")[2]}
    return {"op": op, "topic": topic}


async def _handle(
    socket: WebSocket, engine: Any, user_id: uuid.UUID, frame: object
) -> None:
    if not isinstance(frame, dict):
        await socket.send_json({"op": "error", "code": "bad_frame"})
        return
    op = frame.get("op")
    if op == "ping":
        await socket.send_json({"op": "pong"})
        return
    if op not in ("subscribe", "unsubscribe"):
        await socket.send_json({"op": "error", "code": "unknown_op"})
        return
    topic, legacy = _requested_topic(frame)
    if topic is None:
        code = "room_id_invalid" if legacy else "topic_invalid"
        await socket.send_json({"op": "error", "code": code})
        return
    if op == "unsubscribe":
        hub.unsubscribe(topic, socket)
        await socket.send_json(_reply("unsubscribed", topic, legacy))
        return
    # The own user topic is joined on connect; nobody subscribes to another's.
    parsed = parse_topic(topic)
    if parsed is not None and parsed[0] == USER:
        allowed = parsed[1] == user_id
    else:
        # Checked on every subscribe, so a topic that was lost cannot be joined again.
        allowed = await run_in_threadpool(_allowed, engine, topic, user_id)
    if not allowed:
        code = "room_not_found" if legacy else "topic_not_found"
        await socket.send_json({"op": "error", "code": code})
        return
    hub.subscribe(topic, socket)
    await socket.send_json(_reply("subscribed", topic, legacy))


@router.websocket("/ws")
@router.websocket("/ws/chat")
async def realtime_socket(
    websocket: WebSocket, ticket: str = Query(default="")
) -> None:
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
                    await websocket.send_json({"op": "error", "code": "bad_frame"})
                    continue
                await _handle(websocket, engine, user_id, frame)
        if scope.cancelled_caught:
            await websocket.close(code=EXPIRED_CLOSE)
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(websocket)
