"""Write-side gates for chat safety: timeouts and the attachment policy.

DM rooms are exempt from both: an org timeout or file policy governs the
org's shared rooms, not private conversations between two members.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from chat.permissions import ATTACH, holds_chat_permission
from chat.safety_interfaces import ChatSafetyStore, TimeoutRecord
from core.exceptions_chat import ChatAttachRestrictedError, ChatTimedOutError
from core.security import utc_aware

if TYPE_CHECKING:
    from chat.rooms import RoomCtx
    from rbac.interfaces import AccessControl


def active_timeout(
    store: ChatSafetyStore, org_id: UUID, user_id: UUID
) -> TimeoutRecord | None:
    """The member's timeout when it has not expired yet."""
    row = store.get_timeout(org_id, user_id)
    if row is None:
        return None
    until = utc_aware(row.until)
    if until is None or until <= datetime.now(timezone.utc):
        return None
    return row


class SafetyGate:
    """Raises before a message or upload is accepted."""

    def __init__(self, store: ChatSafetyStore, access: "AccessControl") -> None:
        self._store = store
        self._access = access

    def check_timeout(self, ctx: "RoomCtx", actor_id: UUID) -> None:
        if ctx.dm is not None or ctx.org.owner_id == actor_id:
            return
        row = active_timeout(self._store, ctx.org.id, actor_id)
        if row is not None:
            until = utc_aware(row.until)
            raise ChatTimedOutError(
                f"You are muted in chat until {until.isoformat()}."  # type: ignore[union-attr]
            )

    def check_attach(self, ctx: "RoomCtx", actor_id: UUID) -> None:
        if ctx.dm is not None or ctx.org.owner_id == actor_id:
            return
        if not self._store.attach_restricted(ctx.org.id):
            return
        if not holds_chat_permission(self._access, ctx.org.id, actor_id, ATTACH):
            raise ChatAttachRestrictedError(
                "Attachments are limited to members allowed to attach files."
            )
