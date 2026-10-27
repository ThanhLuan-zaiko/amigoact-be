"""Chat safety errors (split from exceptions.py to keep it under cap)."""

from __future__ import annotations

from core.exceptions import DomainError


class ChatTimedOutError(DomainError):
    """The sender is muted in this org's chat for now."""

    code = "CHAT_TIMED_OUT"
    status = 403


class ChatAttachRestrictedError(DomainError):
    """The org limits attachments and the sender lacks chat:attach."""

    code = "CHAT_ATTACH_RESTRICTED"
    status = 403
