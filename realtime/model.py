"""cqlengine models for the realtime bounded context (persistence only)."""

from __future__ import annotations

import core.database  # noqa: F401  (reactor compat shim must run first)
from cassandra.cqlengine import columns, models


class WsTicket(models.Model):
    """One-time WS handshake ticket. Hash only, self-expiring via TTL."""

    __table_name__ = "ws_tickets"

    ticket_hash = columns.Text(primary_key=True)
    user_id = columns.UUID(required=True)
    expires_at = columns.DateTime(required=True)
    created_at = columns.DateTime(required=True)
