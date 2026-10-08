"""Pydantic DTOs for realtime REST endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class WsTicketResponse(BaseModel):
    """Plaintext one-time ticket, shown once to the authenticated caller."""

    ticket: str
    expires_in: int
