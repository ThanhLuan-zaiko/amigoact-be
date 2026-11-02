"""One-time tickets that let a browser open the chat socket without its access token in the URL."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.chat.rules import TICKET_LIFETIME
from src.chat.schemas import TicketResponse
from src.models.auth import User
from src.models.chat import WsTicket


def _hash(ticket: str) -> str:
    return hashlib.sha256(ticket.encode("utf-8")).hexdigest()


def issue_ticket(db: Session, user_id: uuid.UUID) -> TicketResponse:
    ticket = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + TICKET_LIFETIME
    db.add(WsTicket(ticket_hash=_hash(ticket), user_id=user_id, expires_at=expires_at))
    db.commit()
    return TicketResponse(ticket=ticket, expires_at=expires_at)


def consume_ticket(engine: Engine, ticket: str) -> uuid.UUID | None:
    """Spend the ticket. It works once, and only if it has not expired and its owner is active."""
    if not ticket or len(ticket) > 100:
        return None
    with Session(engine) as db:
        user_id = db.scalar(
            delete(WsTicket)
            .where(
                WsTicket.ticket_hash == _hash(ticket),
                WsTicket.expires_at > datetime.now(UTC),
            )
            .returning(WsTicket.user_id)
        )
        if user_id is None:
            db.rollback()
            return None
        active = db.scalar(select(User.status).where(User.id == user_id)) == "active"
        db.commit()
    return user_id if active else None
