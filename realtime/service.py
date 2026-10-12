"""Business rules for realtime: ticket lifecycle and channel ACLs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta, timezone
from uuid import UUID

from core.realtime import PUBLIC_CHANNEL_SUBJECTS, Channel
from core.security import hash_token, new_opaque_token, utcnow
from realtime.interfaces import (
    AttendanceAccess,
    ChatRoomAccess,
    OrgMembership,
    PresenceDirectory,
    WsTicketStore,
)


@dataclass(frozen=True)
class IssuedTicket:
    """Plaintext ticket plus TTL handed back to the REST caller."""

    token: str
    expires_in: int


class RealtimeService:
    """Ticket lifecycle plus per-channel authorization (16.2, 16.3)."""

    def __init__(
        self,
        tickets: WsTicketStore,
        membership: OrgMembership,
        attendance: AttendanceAccess | None,
        ticket_ttl_seconds: int,
        presence: PresenceDirectory | None = None,
        chat_rooms: ChatRoomAccess | None = None,
    ) -> None:
        self._tickets = tickets
        self._membership = membership
        self._attendance = attendance
        self._ticket_ttl = ticket_ttl_seconds
        self._presence = presence
        self._chat_rooms = chat_rooms

    def issue_ticket(self, user_id: UUID) -> IssuedTicket:
        """Mint an opaque ticket; only its SHA-256 hash is persisted."""
        token = new_opaque_token()
        now = utcnow()
        self._tickets.create(
            ticket_hash=hash_token(token),
            user_id=user_id,
            expires_at=now + timedelta(seconds=self._ticket_ttl),
            now=now,
        )
        return IssuedTicket(token=token, expires_in=self._ticket_ttl)

    def consume_ticket(self, token: str) -> UUID | None:
        """Bind a socket to a user. Expired or spent tickets return None.

        User status (active/suspended) is enforced in the router after
        consume to avoid a circular import on the user repository.
        TODO: inject a UserLookup port here once auth exposes one.
        """
        if not token or not token.strip():
            return None
        row = self._tickets.consume(hash_token(token))
        if row is None:
            return None
        expires_at = row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= utcnow():
            return None
        return row.user_id

    def authorize(self, channel: Channel, user_id: UUID | None) -> bool:
        """Channel ACLs (8: authentication is not authorization).

        Public kinds are open to everyone including guest sockets whose
        user_id is None; every subject-scoped kind requires a user.
        """
        if channel.kind in PUBLIC_CHANNEL_SUBJECTS:
            return True
        if channel.subject is None or user_id is None:
            return False
        if channel.kind == "notifications":
            return channel.subject == user_id
        if channel.kind in ("activities", "members", "posts"):
            return self._membership.is_member(channel.subject, user_id)
        if channel.kind == "chat":
            # Room-aware ACL resolves general/activity/dm rooms; without
            # the port wired, fall back to plain org membership.
            if self._chat_rooms is not None:
                return self._chat_rooms.can_access(channel.subject, user_id)
            return self._membership.is_member(channel.subject, user_id)
        if channel.kind == "attendance":
            return (
                self._attendance.can_view(channel.subject, user_id)
                if self._attendance is not None
                else False
            )
        return False

    def presence_orgs_of(self, user_id: UUID) -> list[UUID]:
        """Orgs that observe this user's presence transitions.

        Empty when the directory port is unwired, so presence silently
        no-ops instead of failing sockets in minimal deployments.
        """
        if self._presence is None:
            return []
        return self._presence.orgs_of(user_id)

    def presence_member_ids(self, org_id: UUID) -> list[UUID]:
        """Active members of one org (the snapshot intersects online ids)."""
        if self._presence is None:
            return []
        return self._presence.member_ids_of(org_id)
