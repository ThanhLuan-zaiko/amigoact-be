"""The "is typing" signal: a socket tells a room it subscribed to that its person is typing.

Nothing is stored. The signal is accepted only on a room topic the socket already
subscribed to, so the access check of the subscribe covers it, and a revoked topic
stops it at once. Each socket may signal a room at most once per TYPING_GAP seconds.
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocket

from src.models.auth import User
from src.realtime.hub import hub
from src.realtime.names import ROOM, parse_topic

TYPING_GAP = 2.0
TYPING_EVENT = "typing"


@dataclass
class SocketState:
    """What one open socket remembers between frames."""

    user_id: uuid.UUID
    name: str | None = None
    last_typing: dict[str, float] = field(default_factory=dict)


def typing_room(topic: object) -> uuid.UUID | None:
    """The room id when the topic is a room topic, the only kind that takes the signal."""
    parsed = parse_topic(topic)
    if parsed is None or parsed[0] != ROOM:
        return None
    return parsed[1]


def due(state: SocketState, topic: str, now: float) -> bool:
    """True when the last signal for this topic is old enough, and records this one."""
    last = state.last_typing.get(topic)
    if last is not None and now - last < TYPING_GAP:
        return False
    state.last_typing[topic] = now
    return True


def typing_event(room_id: uuid.UUID, user_id: uuid.UUID, name: str) -> dict[str, Any]:
    return {
        "type": TYPING_EVENT,
        "room_id": str(room_id),
        "user_id": str(user_id),
        "name": name,
    }


def _full_name(engine: Any, user_id: uuid.UUID) -> str:
    with Session(engine) as db:
        return db.scalar(select(User.full_name).where(User.id == user_id)) or ""


async def signal(
    socket: WebSocket, engine: Any, state: SocketState, frame: dict[str, Any]
) -> None:
    """Tell the other people listening to the room. Errors use the socket error frame."""
    topic = frame.get("topic")
    room_id = typing_room(topic)
    if room_id is None or not isinstance(topic, str):
        await socket.send_json({"op": "error", "code": "topic_invalid"})
        return
    if not hub.is_subscribed(topic, socket):
        await socket.send_json({"op": "error", "code": "topic_not_found"})
        return
    if not due(state, topic, time.monotonic()):
        return
    if state.name is None:
        state.name = await run_in_threadpool(_full_name, engine, state.user_id)
    event = typing_event(room_id, state.user_id, state.name)
    await hub.broadcast_except(topic, event, state.user_id)
