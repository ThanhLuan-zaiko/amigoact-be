"""cqlengine persistence for realtime. Ticket consume uses LWT raw CQL."""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from cassandra.cqlengine.connection import get_session

from realtime.interfaces import WsTicketStore
from realtime.model import WsTicket

_KEYSPACE_RE = re.compile(r"^[a-z0-9_]+$")


def _checked_keyspace(keyspace: str) -> str:
    """Reject unsafe keyspaces before interpolating them into raw CQL."""
    if not _KEYSPACE_RE.match(keyspace):
        raise ValueError("Invalid keyspace name.")
    return keyspace


class CqlWsTicketStore(WsTicketStore):
    """Single-use ticket rows with atomic DELETE ... IF EXISTS consume."""

    def __init__(self, keyspace: str) -> None:
        self._keyspace = _checked_keyspace(keyspace)

    def create(
        self,
        ticket_hash: str,
        user_id: UUID,
        expires_at: datetime,
        now: datetime,
    ) -> None:
        WsTicket.create(
            ticket_hash=ticket_hash,
            user_id=user_id,
            expires_at=expires_at,
            created_at=now,
        )

    def consume(self, ticket_hash: str) -> WsTicket | None:
        row = WsTicket.objects(ticket_hash=ticket_hash).first()
        if row is None:
            return None
        # Single use: raw LWT because cqlengine cannot express an atomic
        # read-and-delete. Second consumer loses the race -> None.
        keyspace = _checked_keyspace(self._keyspace)
        applied = get_session().execute(
            f"DELETE FROM {keyspace}.ws_tickets"
            " WHERE ticket_hash = %s IF EXISTS",
            [ticket_hash],
        )
        if not applied.was_applied:
            return None
        return row
