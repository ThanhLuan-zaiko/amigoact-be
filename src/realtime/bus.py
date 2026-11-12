"""Sending live events and cutting lost topics, in step with the database.

emit and revoke join the caller's transaction:
- This process delivers them to its own sockets right after the commit.
- Other worker processes get them through PostgreSQL NOTIFY, which the database
  also sends only on commit. A rolled back change sends nothing anywhere.

publish is for code that already committed; it delivers at once.
Events are small signals. A page that needs data fetches it through the API,
which checks access again.
"""

import json
import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import anyio.from_thread
from anyio.lowlevel import EventLoopToken
from sqlalchemy import event, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from src.realtime.hub import hub

logger = logging.getLogger(__name__)

CHANNEL = "amigo_realtime"
# PostgreSQL refuses NOTIFY payloads of 8000 bytes or more.
PAYLOAD_LIMIT = 7900
_QUEUED = "realtime_queue"


@dataclass
class _Runtime:
    origin: str = uuid.uuid4().hex
    engine: Engine | None = None
    token: EventLoopToken | None = None


runtime = _Runtime()


def configure(engine: Engine | None, token: EventLoopToken | None) -> None:
    """Called at startup with the event loop that owns the sockets."""
    runtime.engine = engine
    runtime.token = token


def emit_message(topic: str, body: dict[str, Any]) -> dict[str, Any]:
    return {"o": runtime.origin, "k": "emit", "t": topic, "e": body}


def revoke_message(user_id: uuid.UUID, topics: list[str]) -> dict[str, Any]:
    return {"o": runtime.origin, "k": "revoke", "u": str(user_id), "ts": topics}


def encode(message: dict[str, Any]) -> str:
    """An event too large for NOTIFY becomes a resync signal: the page refetches."""
    payload = json.dumps(message, separators=(",", ":"))
    if len(payload.encode()) < PAYLOAD_LIMIT:
        return payload
    slim = {**message, "e": {"type": "resync", "was": message["e"].get("type")}}
    return json.dumps(slim, separators=(",", ":"))


def _notify(connection: Session | Connection, message: dict[str, Any]) -> None:
    connection.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": CHANNEL, "payload": encode(message)},
    )


def deliver_event(topic: str, body: dict[str, Any]) -> None:
    """To this process's sockets. A lost event only delays a page until it refreshes."""
    if not hub.has_listeners(topic):
        return
    try:
        anyio.from_thread.run(hub.broadcast, topic, body, token=runtime.token)
    except RuntimeError:
        logger.debug("Skipped a live event outside the server")


def deliver_revoke(user_id: uuid.UUID, topics: list[str]) -> None:
    if not hub.is_online(user_id):
        return
    try:
        anyio.from_thread.run(hub.revoke, topics, user_id, token=runtime.token)
    except RuntimeError:
        logger.debug("Skipped a live revoke outside the server")


def emit(db: Session, topic: str, body: dict[str, Any]) -> None:
    """Send an event on topic once the caller's transaction commits."""
    db.info.setdefault(_QUEUED, []).append(("emit", topic, body))
    if runtime.engine is not None:
        _notify(db, emit_message(topic, body))


def revoke(db: Session, user_id: uuid.UUID, topics: Iterable[str]) -> None:
    """Stop someone's open sockets from hearing topics, once the change is saved."""
    names = list(topics)
    db.info.setdefault(_QUEUED, []).append(("revoke", user_id, names))
    if runtime.engine is not None:
        _notify(db, revoke_message(user_id, names))


def publish(topic: str, body: dict[str, Any]) -> None:
    """For changes that are already committed."""
    deliver_event(topic, body)
    if runtime.engine is None:
        return
    try:
        with runtime.engine.begin() as connection:
            _notify(connection, emit_message(topic, body))
    except Exception:
        logger.exception("Could not send a live event to other workers")


def revoke_committed(user_id: uuid.UUID, topics: Iterable[str]) -> None:
    """For access that was already taken away and committed."""
    names = list(topics)
    deliver_revoke(user_id, names)
    if runtime.engine is None:
        return
    try:
        with runtime.engine.begin() as connection:
            _notify(connection, revoke_message(user_id, names))
    except Exception:
        logger.exception("Could not send a live revoke to other workers")


@event.listens_for(Session, "after_commit")
def _deliver_queue(session: Session) -> None:
    for kind, first, second in session.info.pop(_QUEUED, []):
        if kind == "emit":
            deliver_event(first, second)
        else:
            deliver_revoke(first, second)


@event.listens_for(Session, "after_rollback")
def _drop_queue(session: Session) -> None:
    session.info.pop(_QUEUED, None)
