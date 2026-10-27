"""Chat permission gates: the three split codes plus the legacy umbrella.

chat:manage predates the split and still implies every part, so each gate
accepts either the specific code or chat:manage. The org owner always passes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from rbac.implied import holds

if TYPE_CHECKING:
    from orgs.model import Organization
    from rbac.interfaces import AccessControl

MODERATE = "chat:moderate"
TIMEOUT = "chat:timeout"
ATTACH = "chat:attach"
MENTION_ALL = "chat:mention-all"
CHANNEL = "chat:channel"
VIEW_PRIVATE = "chat:view-private"


def holds_chat_permission(
    access: "AccessControl", org_id: UUID, user_id: UUID, code: str
) -> bool:
    """True when the user holds `code` or the legacy chat:manage umbrella."""
    return holds(access, org_id, user_id, code)


def owner_or_chat_permission(
    access: "AccessControl", org: "Organization", user_id: UUID, code: str
) -> bool:
    return org.owner_id == user_id or holds_chat_permission(
        access, org.id, user_id, code
    )
