"""Receiving the events other worker processes sent through PostgreSQL NOTIFY.

One thread per process keeps a dedicated connection on LISTEN. Messages this
process sent itself are skipped, because it delivered them right after commit.
"""

import json
import logging
import threading
import uuid
from typing import Any

import psycopg
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from src.realtime import bus

logger = logging.getLogger(__name__)

RETRY_SECONDS = 2.0
WAIT_SECONDS = 5.0


def handle(payload: str) -> None:
    """Pass one NOTIFY payload on to this process's sockets."""
    try:
        message: dict[str, Any] = json.loads(payload)
    except ValueError:
        return
    if not isinstance(message, dict) or message.get("o") == bus.runtime.origin:
        return
    if message.get("k") == "emit" and isinstance(message.get("e"), dict):
        bus.deliver_event(str(message.get("t")), message["e"])
    elif message.get("k") == "revoke" and isinstance(message.get("ts"), list):
        try:
            user_id = uuid.UUID(str(message.get("u")))
        except ValueError:
            return
        bus.deliver_revoke(user_id, [str(topic) for topic in message["ts"]])


class Listener:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._url = engine.url.set(drivername="postgresql").render_as_string(
            hide_password=False
        )
        self._stopped = threading.Event()
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="realtime-listener", daemon=True
        )

    def start(self) -> None:
        self._thread.start()
        if not self._ready.wait(WAIT_SECONDS):
            logger.warning("Realtime listener is not ready; other workers stay silent")

    def stop(self) -> None:
        self._stopped.set()
        # Wake the listening connection so the thread ends at once.
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    text("SELECT pg_notify(:channel, :payload)"),
                    {"channel": bus.CHANNEL, "payload": '{"k":"wake"}'},
                )
        except SQLAlchemyError:
            logger.debug("Could not wake the realtime listener")
        self._thread.join(WAIT_SECONDS)

    def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                with psycopg.connect(self._url, autocommit=True) as connection:
                    connection.execute(f"LISTEN {bus.CHANNEL}")
                    self._ready.set()
                    while not self._stopped.is_set():
                        for notice in connection.notifies(timeout=WAIT_SECONDS):
                            if self._stopped.is_set():
                                return
                            handle(notice.payload)
            except Exception:
                logger.exception("Realtime listener lost its connection")
                self._stopped.wait(RETRY_SECONDS)
